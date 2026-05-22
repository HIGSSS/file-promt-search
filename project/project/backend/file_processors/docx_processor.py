"""Процессор Word-документов через python-docx.

Ограничение: python-docx не читает .doc (бинарный формат Word 97–2003).
Для .doc нужен LibreOffice/antiword — вынесено в направления развития.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

import numpy as np

from models import get_sbert
from utils import chunk_words, l2_normalize, safe_preview

logger = logging.getLogger(__name__)


def _encode_chunks(chunks: list[str]) -> Optional[np.ndarray]:
    if not chunks:
        return None
    sbert = get_sbert()
    vectors = sbert.encode(chunks, convert_to_numpy=True, show_progress_bar=False)
    return l2_normalize(np.mean(vectors, axis=0))


def process(path: Path) -> Optional[dict[str, Any]]:
    """Извлекает текст из .docx и возвращает SBERT-вектор."""
    try:
        import docx  # python-docx
    except ImportError:
        logger.error("python-docx не установлен: pip install python-docx")
        return None

    # .doc (старый бинарный формат) python-docx не откроет — пропускаем.
    if path.suffix.lower() == ".doc":
        logger.info("Пропущен .doc (формат не поддерживается): %s", path)
        return None

    try:
        doc = docx.Document(str(path))
    except Exception as exc:
        logger.warning("Не удалось открыть docx %s: %s", path, exc)
        return None

    # Только параграфы с непустым текстом. Таблицы в docx — отдельная
    # структура (doc.tables); для простоты оставлены вне индексации,
    # поскольку ТЗ требует именно абзацы.
    lines = [p.text for p in doc.paragraphs if p.text.strip()]
    combined = "\n".join(lines).strip()
    if not combined:
        return None

    text_vec = _encode_chunks(chunk_words(combined))
    if text_vec is None:
        return None

    return {
        "text_vec": text_vec,
        "text_preview": safe_preview(combined, max_chars=150),
    }
