"""Поиск по индексам FAISS с гибридным скорингом.

Ключевое решение: FAISS возвращает векторы как отдельные результаты,
а один файл может иметь два вектора (image + OCR-text) в РАЗНЫХ индексах.
Формулу `score = 0.6*image + 0.4*text` из ТЗ нельзя применить к одному
результату FAISS напрямую — нужно сначала собрать все векторы одного
файла, потом применить формулу.

Алгоритм search():
    1. Кодируем запрос в два разных вектора (SigLIP-text для media,
       SBERT для text_index) — зависит от file_type.
    2. Ищем top_k * CANDIDATE_MULTIPLIER в каждом релевантном индексе.
    3. Агрегируем по filepath: {filepath -> {image_sim, text_sim, meta}}.
    4. Применяем формулу скоринга.
    5. Подстрочный бонус, фильтрация удалённых файлов, сортировка, top_k.

Перезагрузка индекса (reload) — из того же процесса, атомарно под локом.
"""
from __future__ import annotations

import logging
import os
import pickle
import re
import threading
import time
from typing import Any, Optional

import faiss
import numpy as np
import torch

from config import (
    CANDIDATE_MULTIPLIER,
    EXACT_MATCH_BONUS,
    IMAGE_WEIGHT,
    MEDIA_INDEX_PATH,
    MEDIA_META_PATH,
    MEDIA_MIN_SCORE,
    SBERT_QUERY_PREFIX,
    SIGLIP_SCORE_MIN,
    SIGLIP_SCORE_RANGE,
    TEXT_INDEX_PATH,
    TEXT_META_PATH,
    TEXT_MIN_SCORE,
    TEXT_WEIGHT,
)
from models import DEVICE, get_sbert, get_siglip, translate_to_english
from schemas import SearchResult
from utils import l2_normalize

logger = logging.getLogger(__name__)

# Паттерн «не-буква/цифра» для обоих алфавитов — используется как граница слова.
_NON_WORD = re.compile(r'[^а-яёА-ЯЁa-zA-Z0-9]')


def _whole_word_match(query: str, text: str) -> bool:
    """True если query встречается в text как отдельное слово, а не подстрока.

    Стандартный \\b не работает с кириллицей, поэтому проверяем окружение
    вручную: символ перед и после совпадения должен быть не буквой/цифрой
    или границей строки.
    """
    if not query or not text:
        return False
    pattern = r'(?<![а-яёА-ЯЁa-zA-Z0-9])' + re.escape(query) + r'(?![а-яёА-ЯЁa-zA-Z0-9])'
    return bool(re.search(pattern, text))

# Лок разделяет загрузку индекса и его использование: reload() не должен
# подменять индексы посередине чужого search(). RLock не нужен — поиск
# не перезагружает индекс изнутри себя.
_lock = threading.Lock()

_media_index: Optional[faiss.Index] = None
_text_index: Optional[faiss.Index] = None
_media_meta: dict[int, dict[str, Any]] = {}
_text_meta: dict[int, dict[str, Any]] = {}


def reload() -> bool:
    """Загружает индексы и метаданные с диска. Безопасна для повторных вызовов.

    Возвращает True, если оба индекса загружены; False, если их нет
    (индексация ещё не запускалась — /search вернёт 400).
    """
    global _media_index, _text_index, _media_meta, _text_meta
    with _lock:
        paths = [MEDIA_INDEX_PATH, TEXT_INDEX_PATH, MEDIA_META_PATH, TEXT_META_PATH]
        if not all(p.exists() for p in paths):
            logger.info("Индексы ещё не построены — поиск вернёт 400")
            _media_index = None
            _text_index = None
            _media_meta = {}
            _text_meta = {}
            return False
        try:
            _media_index = faiss.read_index(str(MEDIA_INDEX_PATH))
            _text_index = faiss.read_index(str(TEXT_INDEX_PATH))
            with open(MEDIA_META_PATH, "rb") as f:
                _media_meta = pickle.load(f)
            with open(TEXT_META_PATH, "rb") as f:
                _text_meta = pickle.load(f)
            logger.info(
                "Индексы загружены: media=%s, text=%s",
                _media_index.ntotal, _text_index.ntotal,
            )
            return True
        except Exception:
            logger.exception("Не удалось загрузить индексы")
            _media_index = None
            _text_index = None
            _media_meta = {}
            _text_meta = {}
            return False


def is_loaded() -> bool:
    """True, если индексы готовы к поиску."""
    with _lock:
        return _media_index is not None and _text_index is not None


# --- Кодирование запроса ------------------------------------------------


def _encode_query_siglip(query: str) -> np.ndarray:
    """Текст → SigLIP text-вектор (dim=768) для поиска по media_index.

    ВАЖНО: padding='max_length' обязателен — SigLIP обучался с фиксированной
    длиной 64 токена. С padding=True короткие запросы дают некорректные
    векторы (отрицательное cosine-сходство вместо ожидаемого ~0.09).
    """
    english_query = translate_to_english(query)
    # Шаблон "a photo of X" значительно улучшает cosine-сходство с SigLIP:
    # диагностика показала "cat"→3%, "a photo of a cat"→14.5% для той же фото.
    raw = english_query.strip().rstrip(".").lower()
    # Добавляем артикль "a/an" перед существительными если нет предлогов
    template = (
        f"a photo of {raw}"
        if not any(raw.startswith(p) for p in ("a ", "an ", "the ", "photo", "image", "picture"))
        else raw
    )
    model, processor = get_siglip()
    inputs = processor(
        text=[template],
        return_tensors="pt",
        padding="max_length",
        truncation=True,
    )
    inputs = {k: v.to(DEVICE) for k, v in inputs.items()}
    with torch.no_grad():
        features = model.get_text_features(**inputs)
    return l2_normalize(features[0].cpu().numpy())


def _encode_query_sbert(query: str) -> np.ndarray:
    """Текст → SBERT-вектор (dim=384) для поиска по text_index."""
    sbert = get_sbert()
    to_encode = SBERT_QUERY_PREFIX + query if SBERT_QUERY_PREFIX else query
    vec = sbert.encode(to_encode, convert_to_numpy=True, show_progress_bar=False)
    return l2_normalize(vec)


# --- Агрегация и скоринг ------------------------------------------------


def _search_index(
    index: faiss.Index, query_vec: np.ndarray, k: int
) -> list[tuple[int, float]]:
    """Обёртка над FAISS search. Возвращает (id, similarity) отсортированный."""
    if index.ntotal == 0:
        return []
    k_effective = min(k, index.ntotal)
    # FAISS требует (1, D) float32 contiguous.
    q = np.ascontiguousarray(query_vec.reshape(1, -1).astype(np.float32))
    sims, ids = index.search(q, k_effective)
    return [
        (int(idx), float(sim))
        for idx, sim in zip(ids[0], sims[0])
        if idx != -1
    ]


def _filter_by_type(
    hits: list[tuple[int, float]],
    meta: dict[int, dict[str, Any]],
    allowed_types: Optional[set[str]],
) -> list[tuple[int, float]]:
    """Оставляет только hits, чей filetype входит в allowed_types.

    None = без фильтра (используется, когда file_type='all' или выборка уже
    идёт из нужного индекса).
    """
    if allowed_types is None:
        return hits
    return [
        (fid, sim) for fid, sim in hits
        if meta.get(fid, {}).get("type") in allowed_types
    ]


def search(
    query: str,
    file_type: str,
    top_k: int,
    min_score: float = 0.5,
) -> list[SearchResult]:
    """Семантический поиск с агрегацией и гибридным скорингом.

    file_type:
        'media'     → поиск только по media_index
        'documents' → поиск только по text_index, типы pdf/docx/txt
        'other'     → поиск только по text_index, типы csv/xlsx/other
        'all'       → оба индекса, все типы

    Стратегия выдачи:
        Возвращаются все результаты с score >= min_score.
        Если таких меньше top_k — добавляются лучшие результаты ниже порога,
        пока не наберётся top_k (или не кончатся кандидаты).
    """
    with _lock:
        media_index = _media_index
        text_index = _text_index
        media_meta = dict(_media_meta)  # копия для работы вне лока
        text_meta = dict(_text_meta)

    if media_index is None or text_index is None:
        raise RuntimeError("Индекс не загружен")

    # Ищем достаточно глубоко, чтобы не пропустить результаты выше порога.
    # _search_index ограничит k до index.ntotal автоматически.
    k_candidates = max(top_k * CANDIDATE_MULTIPLIER, 500)

    # Определяем, в какие индексы идём и с какими фильтрами типов.
    use_media = file_type in ("media", "documents", "all")
    use_text = file_type in ("documents", "other", "all")

    if file_type == "documents":
        # Документы — это только pdf и docx. Всё остальное (txt, таблицы,
        # презентации, разметка и т.д.) пользователь относит к «прочему».
        text_type_filter: Optional[set[str]] = {"pdf", "docx"}
    elif file_type == "other":
        # Всё, что не медиа (image/video — в media_index) и не pdf/docx:
        # текстовые форматы, таблицы, офисные форматы и нераспознанные типы.
        text_type_filter = {
            "txt", "csv", "xlsx", "xls", "pptx", "odt", "rtf",
            "md", "markdown", "json", "xml", "html", "htm", "log", "other",
        }
    else:
        text_type_filter = None  # media или all — не фильтруем

    # Агрегатор по filepath. Для каждого файла собираем лучший
    # image_sim и лучший text_sim (если было несколько hits одного вида).
    aggregated: dict[str, dict[str, Any]] = {}

    if use_media:
        q_siglip = _encode_query_siglip(query)
        media_hits = _search_index(media_index, q_siglip, k_candidates)
        for fid, sim in media_hits:
            rec = media_meta.get(fid)
            if rec is None:
                continue
            if file_type == "documents" and rec.get("type") != "pdf":
                continue
            fp = rec["filepath"]
            entry = aggregated.setdefault(
                fp, {"image_sim": None, "text_sim": None, "meta": rec}
            )
            prev = entry["image_sim"]
            if prev is None or sim > prev:
                entry["image_sim"] = sim
                # Обновляем meta только если ранее его не было (media
                # и text meta для одного файла имеют одинаковые filepath/type).

    if use_text:
        q_sbert = _encode_query_sbert(query)
        text_hits = _search_index(text_index, q_sbert, k_candidates)
        text_hits = _filter_by_type(text_hits, text_meta, text_type_filter)
        for fid, sim in text_hits:
            rec = text_meta.get(fid)
            if rec is None:
                continue
            fp = rec["filepath"]
            entry = aggregated.setdefault(
                fp, {"image_sim": None, "text_sim": None, "meta": rec}
            )
            prev = entry["text_sim"]
            if prev is None or sim > prev:
                entry["text_sim"] = sim
                # Если предыдущий meta был из media — перезаписываем тем,
                # где есть text_preview (важно для UI подсказок).
                if rec.get("text_preview"):
                    entry["meta"] = rec

    # Точный поиск по имени файла: поднимает файлы вроде IMG_0002.jpg
    # которые векторный поиск не находит в top-N кандидатов.
    # ВАЖНО: используем целое слово, а не подстроку — иначе «кот» совпадает
    # с «который» и все документы с этим словом получают score 0.95.
    if query_lower := query.lower():
        meta_sources: list[dict[int, dict[str, Any]]] = []
        if use_media:
            meta_sources.append(media_meta)
        if use_text:
            meta_sources.append(text_meta)
        for source in meta_sources:
            for rec in source.values():
                if source is text_meta and text_type_filter is not None:
                    if rec.get("type") not in text_type_filter:
                        continue
                filename = rec.get("filename", "")
                # Только по имени файла (целое слово) — не по содержимому превью.
                if not _whole_word_match(query_lower, filename.lower()):
                    continue
                fp = rec["filepath"]
                entry = aggregated.setdefault(
                    fp, {"image_sim": None, "text_sim": None, "meta": rec}
                )
                prev = entry["text_sim"]
                # В режиме «other» поиск идёт в первую очередь по имени:
                # точное совпадение в названии = максимальный скор.
                boost = 0.98 if file_type == "other" else 0.95
                if prev is None or prev < boost:
                    entry["text_sim"] = boost
                    entry["meta"] = rec

    # Применяем формулу скоринга.
    scored: list[tuple[float, dict[str, Any]]] = []
    for fp, entry in aggregated.items():
        image_sim = entry["image_sim"]
        text_sim = entry["text_sim"]

        # SigLIP text-image cosines: [0, ~0.35] для хорошего совпадения,
        # тогда как SBERT даёт 0.5–0.9. Нормализуем SigLIP в [0, 1].
        scaled_image = None
        if image_sim is not None:
            scaled_image = max(0.0, min(image_sim / SIGLIP_SCORE_RANGE, 1.0))

        if scaled_image is not None and text_sim is not None:
            # Зажимаем text_sim в [0, 1]: отрицательные сходства возникают
            # при несовместимости модели (старый индекс + новый SBERT).
            # Они не должны гасить корректный image_sim.
            score = IMAGE_WEIGHT * scaled_image + TEXT_WEIGHT * max(0.0, text_sim)
        elif scaled_image is not None:
            score = scaled_image
        else:
            score = max(0.0, text_sim)  # type: ignore[assignment]

        # Бонус только за целое слово в имени файла или превью.
        if query_lower:
            preview = entry["meta"].get("text_preview") or ""
            filename_str = entry["meta"].get("filename") or os.path.basename(fp)
            if _whole_word_match(query_lower, preview.lower()):
                score += EXACT_MATCH_BONUS
            if _whole_word_match(query_lower, filename_str.lower()):
                score += EXACT_MATCH_BONUS

        scored.append((score, entry["meta"]))

    # Сортируем по убыванию скора, фильтруем удалённые файлы.
    scored.sort(key=lambda x: x[0], reverse=True)

    # Стратегия выдачи:
    #   1. Берём все кандидаты с score >= min_score.
    #   2. Если их меньше top_k — дополняем лучшими результатами ниже порога
    #      до top_k (чтобы экран никогда не был пустым при слабом запросе).
    above = [(s, m) for s, m in scored if s >= min_score]
    candidates = above if len(above) >= top_k else scored[:top_k]

    results: list[SearchResult] = []
    for score, meta in candidates:
        fp = meta["filepath"]
        # os.path.exists — дешёвый системный вызов; делаем после сортировки,
        # чтобы не проверять существование у кандидатов, которые и так отсеются.
        if not os.path.exists(fp):
            continue
        results.append(
            SearchResult(
                filepath=fp,
                filename=meta.get("filename", os.path.basename(fp)),
                type=meta.get("type", "other"),
                # Зажимаем в [0..1]: косинусное сходство может быть отрицательным
                # (противоположный смысл), бонус может поднять выше 1.0.
                score=max(0.0, min(float(score), 1.0)),
                text_preview=meta.get("text_preview"),
            )
        )

    return results


def measure_search(
    query: str, file_type: str, top_k: int, min_score: float = 0.5
) -> tuple[list[SearchResult], int]:
    """То же, что search(), но возвращает (results, elapsed_ms) для /search ответа."""
    t0 = time.perf_counter()
    results = search(query, file_type, top_k, min_score)
    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    return results, elapsed_ms
