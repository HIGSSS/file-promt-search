"""Индексатор: обходит директорию, вызывает процессоры, строит FAISS-индексы.

Thread-safety:
    * index_state защищён _state_lock; все чтения/записи идут через
      get_status() и _update_state(), никогда напрямую.
    * Параллельный /index во время уже идущей индексации отбивается
      на уровне эндпоинта через try_start() (атомарная смена состояния).
    * Запись индексов атомарна: сначала пишем .tmp, затем os.replace().
      Это защищает searcher'а от чтения полузаписанного индекса.

Структура метаданных:
    Каждый FAISS-индекс хранит векторы под целочисленными id (row number).
    Параллельный метадата-словарь: {faiss_id -> dict с filepath, type, preview}.

    Один файл может иметь ДВА вектора (image + OCR-text) с разными id
    в разных FAISS-индексах. Агрегация по filepath происходит в searcher'е.
"""
from __future__ import annotations

import logging
import os
import pickle
import threading
from pathlib import Path
from typing import Any

import faiss
import numpy as np

from config import (
    MEDIA_INDEX_PATH,
    MEDIA_META_PATH,
    SBERT_DIM,
    SIGLIP_DIM,
    STORAGE_DIR,
    TEXT_INDEX_PATH,
    TEXT_META_PATH,
)
from file_processors import detect_type, process_file
from file_processors.text_processor import encode_filename

logger = logging.getLogger(__name__)

# --- Состояние индексации (thread-safe) ---------------------------------

_state_lock = threading.Lock()
_index_state: dict[str, Any] = {
    "state": "idle",
    "processed": 0,
    "total": 0,
    "current_file": "",
    "error": None,
}


def get_status() -> dict[str, Any]:
    """Возвращает копию текущего состояния. Копия нужна, чтобы вызывающий
    код не смог случайно изменить внутреннее состояние извне лока.
    """
    with _state_lock:
        return dict(_index_state)


def _update_state(**changes: Any) -> None:
    """Атомарно обновляет поля состояния."""
    with _state_lock:
        _index_state.update(changes)


def try_start() -> bool:
    """Пытается перевести состояние 'idle'|'done'|'error' → 'indexing'.

    Возвращает True, если старт успешен. Если уже индексируется — False,
    эндпоинт отвечает 'busy' без запуска нового фонового таска.
    Это защита от повторного нажатия кнопки «Индексировать» в UI.
    """
    with _state_lock:
        if _index_state["state"] == "indexing":
            return False
        _index_state.update(
            state="indexing",
            processed=0,
            total=0,
            current_file="",
            error=None,
        )
        return True


def mark_error(message: str) -> None:
    """Переводит состояние в error, если ошибка произошла до run_indexing().

    Используется endpoint'ами загрузки: они сначала атомарно занимают
    индексатор через try_start(), затем сохраняют файлы. Если сохранение
    падает, фоновой задачи ещё нет, поэтому состояние нужно завершить явно.
    """
    _update_state(state="error", current_file="", error=message)


# --- Атомарная запись индексов ------------------------------------------

# Лок на запись индексов на диск. Searcher при перезагрузке индекса
# берёт тот же лок — чтобы не прочитать полузаписанное состояние.
# (В FastAPI searcher.reload() вызывается из того же потока, что и
#  финал индексации — но лок оставляем на случай будущих изменений.)
_write_lock = threading.Lock()


def _atomic_write_index(index: faiss.Index, target: Path) -> None:
    """Пишет FAISS-индекс через tmp-файл + os.replace (атомарно на POSIX)."""
    tmp = target.with_suffix(target.suffix + ".tmp")
    faiss.write_index(index, str(tmp))
    os.replace(tmp, target)


def _atomic_write_pickle(obj: Any, target: Path) -> None:
    """Пишет pickle через tmp-файл + os.replace."""
    tmp = target.with_suffix(target.suffix + ".tmp")
    with open(tmp, "wb") as f:
        pickle.dump(obj, f, protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(tmp, target)


# --- Основной алгоритм индексации ---------------------------------------


def _collect_files(root: Path) -> list[Path]:
    """Рекурсивно собирает все читаемые файлы ненулевого размера."""
    files: list[Path] = []
    # rglob('*') обходит символические ссылки — это ок: у пользователя
    # могут быть ссылки на внешние хранилища, их тоже хотим проиндексировать.
    for p in root.rglob("*"):
        try:
            if not p.is_file():
                continue
            stat = p.stat()
            if stat.st_size == 0:
                continue
            if not os.access(p, os.R_OK):
                continue
            files.append(p)
        except OSError:
            # Битые симлинки, отказ в доступе к подкаталогу — пропускаем тихо.
            continue
    return files


def _process_one(
    path: Path,
    media_index: faiss.Index,
    text_index: faiss.Index,
    media_meta: dict[int, dict[str, Any]],
    text_meta: dict[int, dict[str, Any]],
) -> None:
    """Обрабатывает один файл и добавляет его векторы в соответствующие индексы.

    Каждый вызов может добавить 0, 1 или 2 вектора (image-only, text-only,
    или оба для изображений с OCR-текстом). id в metadata — это ntotal
    индекса на момент добавления (FAISS.add присваивает последовательные id).
    """
    result = process_file(path)
    filename_result = encode_filename(path)
    used_filename_fallback = False

    # Fallback: если процессор вернул None или пустой результат — индексируем по имени.
    if not result:
        if filename_result is None:
            logger.debug("Нет вектора для %s — пропущен", path)
            return
        used_filename_fallback = True
        result = {
            **filename_result,
            "type": detect_type(path),
        }

    file_type = result.get("type", "other")
    filepath_str = str(path)
    filename = path.name
    preview = result.get("text_preview")

    image_vec = result.get("image_vec")
    text_vec = result.get("text_vec")
    text_chunks = result.get("text_chunks") or []

    if image_vec is not None:
        _add_to_index(
            index=media_index,
            meta=media_meta,
            vec=image_vec,
            expected_dim=SIGLIP_DIM,
            record={
                "filepath": filepath_str,
                "filename": filename,
                "type": file_type,
                "text_preview": preview,
                "vec_kind": "image",
            },
            path=path,
        )

    for chunk_no, chunk in enumerate(text_chunks, start=1):
        chunk_vec = chunk.get("text_vec")
        if chunk_vec is None:
            continue
        _add_to_index(
            index=text_index,
            meta=text_meta,
            vec=chunk_vec,
            expected_dim=SBERT_DIM,
            record={
                "filepath": filepath_str,
                "filename": filename,
                "type": file_type,
                "text_preview": chunk.get("text_preview") or preview,
                "vec_kind": chunk.get("vec_kind", "text_chunk"),
                "chunk_no": chunk_no,
                "chunk_label": chunk.get("chunk_label", ""),
            },
            path=path,
        )

    if text_vec is not None:
        _add_to_index(
            index=text_index,
            meta=text_meta,
            vec=text_vec,
            expected_dim=SBERT_DIM,
            record={
                "filepath": filepath_str,
                "filename": filename,
                "type": file_type,
                "text_preview": preview,
                "vec_kind": "text",
            },
            path=path,
        )

    # Имя файла индексируем всегда, даже если содержимое успешно обработано.
    # Это делает точные запросы вроде IMG_0002 или договор_2024 рабочими.
    if filename_result is not None and not used_filename_fallback:
        filename_vec = filename_result.get("text_vec")
        if filename_vec is not None:
            _add_to_index(
                index=text_index,
                meta=text_meta,
                vec=filename_vec,
                expected_dim=SBERT_DIM,
                record={
                    "filepath": filepath_str,
                    "filename": filename,
                    "type": file_type,
                    "text_preview": preview or filename_result.get("text_preview"),
                    "vec_kind": "filename",
                },
                path=path,
            )


def _add_to_index(
    index: faiss.Index,
    meta: dict[int, dict[str, Any]],
    vec: np.ndarray,
    expected_dim: int,
    record: dict[str, Any],
    path: Path,
) -> None:
    """Добавляет один нормализованный вектор в FAISS и запись в meta-dict."""
    if vec.shape[-1] != expected_dim:
        logger.warning(
            "Размерность вектора для %s не совпадает: %s вместо %s — пропуск",
            path, vec.shape[-1], expected_dim,
        )
        return
    # FAISS ожидает (N, D) float32. reshape обязателен: процессоры
    # возвращают (D,), но FAISS.add требует двумерный батч.
    batch = np.ascontiguousarray(vec.reshape(1, -1).astype(np.float32))
    new_id = index.ntotal  # id будет присвоен FAISS последовательно
    index.add(batch)
    meta[new_id] = record


def run_indexing(directory_path: str, on_finish: Any = None) -> None:
    """Фоновая задача индексации.

    Вызывается из FastAPI BackgroundTasks. try_start() должен быть вызван
    ДО неё в эндпоинте (иначе состояние 'indexing' не выставлено).

    on_finish: опциональный коллбэк (например, searcher.reload), который
    вызывается после успешной записи индексов. Ошибка в коллбэке не
    откатывает индексацию — только логируется.
    """
    try:
        root = Path(directory_path).resolve()
        if not root.is_dir():
            _update_state(state="error", error=f"Директория не найдена: {directory_path}")
            return

        STORAGE_DIR.mkdir(parents=True, exist_ok=True)

        files = _collect_files(root)
        _update_state(total=len(files), processed=0)
        logger.info("Найдено файлов для индексации: %s", len(files))

        # IndexFlatIP: inner product = cosine similarity для нормализованных векторов.
        # Flat — это точный поиск без приближений; достаточно для 10k+ файлов.
        media_index: faiss.Index = faiss.IndexFlatIP(SIGLIP_DIM)
        text_index: faiss.Index = faiss.IndexFlatIP(SBERT_DIM)
        media_meta: dict[int, dict[str, Any]] = {}
        text_meta: dict[int, dict[str, Any]] = {}

        for i, path in enumerate(files):
            _update_state(current_file=path.name, processed=i)
            try:
                _process_one(path, media_index, text_index, media_meta, text_meta)
            except Exception:
                # Ошибка одного файла не должна останавливать индексацию.
                # exc_info=True пишет traceback в лог для последующего анализа.
                logger.exception("Ошибка обработки %s", path)

        _update_state(processed=len(files), current_file="")

        with _write_lock:
            _atomic_write_index(media_index, MEDIA_INDEX_PATH)
            _atomic_write_index(text_index, TEXT_INDEX_PATH)
            _atomic_write_pickle(media_meta, MEDIA_META_PATH)
            _atomic_write_pickle(text_meta, TEXT_META_PATH)

        logger.info(
            "Индексация завершена: media=%s, text=%s",
            media_index.ntotal, text_index.ntotal,
        )
        _update_state(state="done")

        if on_finish is not None:
            try:
                on_finish()
            except Exception:
                logger.exception("Коллбэк on_finish упал (не критично)")

    except Exception as exc:
        logger.exception("Индексация упала")
        _update_state(state="error", error=str(exc))
