"""Диспетчер процессоров файлов.

Один вход в модуль — process_file(path) — возвращает результат обработки
или None, если файл должен быть проиндексирован только по имени.

Результат — это dict со следующими опциональными ключами:
    image_vec: np.ndarray[float32, (768,)]   — нормализованный вектор SigLIP
    text_vec:  np.ndarray[float32, (384,)]   — нормализованный вектор SBERT
    text_preview: str                         — превью для UI и подстрочного бонуса
    type: str                                 — 'image'|'video'|'pdf'|'docx'|'txt'|'csv'|'xlsx'|'other'

Если процессор вернул None или пустой dict — файл индексируется по имени
(fallback в indexer'е через text_processor.encode_filename).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from config import (
    CSV_EXTENSIONS,
    DOCX_EXTENSIONS,
    MEDIA_EXTENSIONS,
    PDF_EXTENSIONS,
    TABLE_EXTENSIONS,
    TEXT_EXTENSIONS,
    VIDEO_EXTENSIONS,
)


def detect_type(path: Path) -> str:
    """Возвращает строковый тип файла по расширению. Нижний регистр обязателен."""
    ext = path.suffix.lower()
    if ext in MEDIA_EXTENSIONS:
        return "image"
    if ext in VIDEO_EXTENSIONS:
        return "video"
    if ext in PDF_EXTENSIONS:
        return "pdf"
    if ext in DOCX_EXTENSIONS:
        return "docx"
    if ext in TEXT_EXTENSIONS:
        return "txt"
    if ext in CSV_EXTENSIONS:
        return "csv"
    if ext in TABLE_EXTENSIONS:
        return "xlsx"
    return "other"


def process_file(path: Path) -> Optional[dict[str, Any]]:
    """Выбирает и запускает нужный процессор. None — fallback на имя файла.

    Импорты процессоров локальные: при обработке изображения нам не нужен
    openpyxl, а при обработке xlsx — opencv. Ленивая загрузка ускоряет старт.
    """
    file_type = detect_type(path)

    if file_type == "image":
        from file_processors.image_processor import process as p
        return _attach_type(p(path), "image")
    if file_type == "video":
        from file_processors.video_processor import process as p
        return _attach_type(p(path), "video")
    if file_type == "pdf":
        from file_processors.pdf_processor import process as p
        return _attach_type(p(path), "pdf")
    if file_type == "docx":
        from file_processors.docx_processor import process as p
        return _attach_type(p(path), "docx")
    if file_type == "txt":
        from file_processors.text_processor import process as p
        return _attach_type(p(path), "txt")
    if file_type == "csv":
        from file_processors.table_processor import process_csv as p
        return _attach_type(p(path), "csv")
    if file_type == "xlsx":
        from file_processors.table_processor import process_xlsx as p
        return _attach_type(p(path), "xlsx")
    # other — индексируется по имени на уровне indexer'а
    return None


def _attach_type(result: Optional[dict[str, Any]], file_type: str) -> Optional[dict[str, Any]]:
    """Добавляет поле 'type' в результат процессора (если он вернул не None)."""
    if result is None:
        return None
    result["type"] = file_type
    return result
