"""Процессор текстовых файлов и fallback-обработчик имён файлов.

encode_filename используется из indexer'а для файлов неизвестного типа,
у которых нет содержимого для векторизации.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

import numpy as np

from config import SBERT_PASSAGE_PREFIX, TEXT_MAX_CHARS
from models import get_sbert
from utils import chunk_words, l2_normalize, safe_preview

logger = logging.getLogger(__name__)


def _encode_chunks(chunks: list[str]) -> Optional[np.ndarray]:
    if not chunks:
        return None
    sbert = get_sbert()
    vectors = sbert.encode(chunks, convert_to_numpy=True, show_progress_bar=False)
    return l2_normalize(np.mean(vectors, axis=0))


def encode_text_chunks(text: str, label_prefix: str = "chunk") -> list[dict[str, Any]]:
    """Encodes every text chunk separately so long documents are searchable by local meaning."""
    chunks = chunk_words(text)
    if not chunks:
        return []
    sbert = get_sbert()
    # E5-модели работают лучше с префиксом "passage: " для индексируемых текстов.
    # Для других моделей SBERT_PASSAGE_PREFIX == "" и поведение не меняется.
    to_encode = [SBERT_PASSAGE_PREFIX + c for c in chunks] if SBERT_PASSAGE_PREFIX else chunks
    vectors = sbert.encode(to_encode, convert_to_numpy=True, show_progress_bar=False)
    encoded: list[dict[str, Any]] = []
    for i, (chunk, vec) in enumerate(zip(chunks, vectors), start=1):
        encoded.append(
            {
                "text_vec": l2_normalize(vec),
                "text_preview": safe_preview(chunk, max_chars=150),
                "chunk_label": f"{label_prefix} {i}",
                "vec_kind": "text_chunk",
            }
        )
    return encoded


def _encode_single(text: str) -> Optional[np.ndarray]:
    if not text.strip():
        return None
    sbert = get_sbert()
    to_encode = SBERT_PASSAGE_PREFIX + text if SBERT_PASSAGE_PREFIX else text
    vec = sbert.encode(to_encode, convert_to_numpy=True, show_progress_bar=False)
    return l2_normalize(vec)


def process(path: Path) -> Optional[dict[str, Any]]:
    """Читает первые TEXT_MAX_CHARS символов и возвращает SBERT-вектор."""
    try:
        # errors='ignore' обязателен: среди .txt часто встречаются
        # файлы в cp1251/cp866/latin-1 без BOM.
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read(TEXT_MAX_CHARS)
    except OSError as exc:
        logger.warning("Не удалось прочитать %s: %s", path, exc)
        return None

    if not text.strip():
        return None

    text_chunks = encode_text_chunks(text)
    if not text_chunks:
        return None

    return {
        "text_chunks": text_chunks,
        "text_preview": safe_preview(text, max_chars=150),
    }


def encode_filename(path: Path) -> Optional[dict[str, Any]]:
    """Fallback: индексирует файл по имени (без расширения).

    Вызывается indexer'ом для файлов неизвестного типа и для файлов,
    чей процессор вернул None (не удалось извлечь содержимое).
    """
    # Берём stem (имя без расширения), заменяем разделители на пробелы,
    # чтобы 'annual_report_2024' превратилось в 'annual report 2024' —
    # SBERT лучше работает с человеческим текстом, чем со snake_case.
    name = path.stem.replace("_", " ").replace("-", " ").strip()
    if not name:
        return None
    text_vec = _encode_single(name)
    if text_vec is None:
        return None
    return {
        "text_vec": text_vec,
        "text_preview": safe_preview(name, max_chars=150),
    }
