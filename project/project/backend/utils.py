"""Общие утилиты: L2-нормализация, чанкование текста, проверка осмысленности.

Все функции чистые, без побочных эффектов и без обращения к моделям.
"""
from __future__ import annotations

from typing import Iterator

import numpy as np

from config import CHUNK_OVERLAP, CHUNK_WORDS


def l2_normalize(vec: np.ndarray) -> np.ndarray:
    """Нормализует вектор по L2-норме до float32.

    Обязательна перед записью в FAISS IndexFlatIP: косинусное сходство
    сводится к скалярному произведению только для векторов единичной длины.
    Для вырожденного случая ||v|| == 0 возвращаем исходный нулевой вектор
    (вместо NaN от деления на ноль).
    """
    vec = np.asarray(vec, dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(vec))
    if norm == 0.0:
        return vec
    return (vec / norm).astype(np.float32)


def chunk_words(text: str, size: int = CHUNK_WORDS, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Разбивает текст на перекрывающиеся чанки по словам.

    Перекрытие нужно, чтобы смысловые единицы, попавшие на границу,
    не терялись. Для коротких текстов возвращается один чанк.
    """
    if not text or not text.strip():
        return []
    if size <= 0:
        raise ValueError("size должен быть > 0")
    if overlap < 0 or overlap >= size:
        raise ValueError("overlap должен быть в диапазоне [0, size)")

    words = text.split()
    if len(words) <= size:
        return [" ".join(words)]

    chunks: list[str] = []
    step = size - overlap
    for start in range(0, len(words), step):
        chunk = words[start : start + size]
        if not chunk:
            break
        chunks.append(" ".join(chunk))
        if start + size >= len(words):
            break
    return chunks


def iter_chunks(text: str) -> Iterator[str]:
    """Генераторная версия chunk_words для экономии памяти на очень длинных текстах."""
    yield from chunk_words(text)


def is_meaningful_text(text: str, min_chars: int = 20, min_long_words: int = 3) -> bool:
    """Проверяет, что текст похож на содержимое, а не на колонтитул/мусор OCR.

    В ТЗ был порог `len(text.strip()) > 20`, который срабатывал на «стр. 5 из 42»
    и помечал сканированные страницы как текстовые. Дополнительное условие:
    есть хотя бы несколько слов длиной > 2 символов.
    """
    stripped = text.strip() if text else ""
    if len(stripped) <= min_chars:
        return False
    long_words = sum(1 for w in stripped.split() if len(w) > 2)
    return long_words >= min_long_words


def safe_preview(text: str, max_chars: int = 150) -> str:
    """Готовит короткий превью текста: обрезка по символам + схлопывание пробелов.

    Нужно для human-readable text_preview в метаданных и в UI.
    """
    if not text:
        return ""
    collapsed = " ".join(text.split())
    if len(collapsed) <= max_chars:
        return collapsed
    return collapsed[:max_chars].rstrip() + "…"
