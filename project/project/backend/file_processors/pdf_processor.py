"""Процессор PDF: текст через PyMuPDF, сканы — через PaddleOCR.

Алгоритм для каждой страницы:
    1. page.get_text() → если осмысленный (is_meaningful_text) — текстовая.
    2. Иначе рендерим страницу в изображение и прогоняем через OCR.
    3. Объединяем текст всех страниц, чанкуем по CHUNK_WORDS слов,
       кодируем каждый чанк SBERT'ом, усредняем, нормализуем.

Использован PyMuPDF (fitz), а не связка PyPDF2 + pdf2image:
    * fitz одновременно извлекает текст и рендерит страницы в пиксели;
    * pdf2image требует системного poppler — лишняя внешняя зависимость;
    * PyPDF2 на некоторых PDF возвращает мусорный текст, fitz стабильнее.
"""
from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Any, Optional

import numpy as np
from PIL import Image

from models import get_ocr, get_sbert
from utils import chunk_words, is_meaningful_text, l2_normalize, safe_preview

logger = logging.getLogger(__name__)

# DPI рендера для OCR. 200 — компромисс скорость/качество: при 150
# мелкий шрифт теряется, при 300 — вдвое медленнее без заметного прироста.
OCR_DPI = 200


def _extract_page_text_or_ocr(page: Any) -> str:
    """Возвращает текст страницы либо из слоя PDF, либо через OCR скана."""
    native_text = page.get_text() or ""
    if is_meaningful_text(native_text, min_chars=20, min_long_words=3):
        return native_text

    # Страница — скан. Рендерим в PIL.Image и отдаём PaddleOCR.
    try:
        import fitz  # noqa: F401 — уже импортирован в process, здесь только для ясности

        # get_pixmap с matrix масштабирует страницу до нужного DPI.
        zoom = OCR_DPI / 72.0  # PDF базовый dpi = 72
        pix = page.get_pixmap(matrix=_zoom_matrix(zoom))
        img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
    except Exception as exc:
        logger.warning("Не удалось отрендерить страницу %s: %s", page.number, exc)
        return ""

    ocr = get_ocr()
    try:
        # PaddleOCR принимает numpy-массив напрямую.
        raw = ocr.ocr(np.array(img), cls=True)
    except Exception as exc:
        logger.warning("OCR упал на странице %s: %s", page.number, exc)
        return ""

    if not raw or not raw[0]:
        return ""
    lines: list[str] = []
    for line in raw[0]:
        try:
            text = line[1][0]
            if text:
                lines.append(text)
        except (IndexError, TypeError):
            continue
    return " ".join(lines)


def _zoom_matrix(zoom: float):
    """Матрица масштабирования для fitz.Page.get_pixmap."""
    import fitz

    return fitz.Matrix(zoom, zoom)


def _encode_chunks(chunks: list[str]) -> Optional[np.ndarray]:
    """Кодирует чанки SBERT'ом, усредняет, нормализует."""
    if not chunks:
        return None
    sbert = get_sbert()
    # SBERT умеет батч-энкодить. convert_to_numpy=True возвращает ndarray.
    vectors = sbert.encode(chunks, convert_to_numpy=True, show_progress_bar=False)
    mean_vec = np.mean(vectors, axis=0)
    return l2_normalize(mean_vec)


def process(path: Path) -> Optional[dict[str, Any]]:
    """Обрабатывает PDF любого типа (текстовый/скан/гибридный)."""
    try:
        import fitz
    except ImportError:
        logger.error("PyMuPDF не установлен: pip install pymupdf")
        return None

    try:
        doc = fitz.open(str(path))
    except Exception as exc:
        # Зашифрованные или битые PDF — просто пропускаем (см. §8 ТЗ).
        logger.warning("Не удалось открыть PDF %s: %s", path, exc)
        return None

    try:
        texts: list[str] = []
        for page in doc:
            page_text = _extract_page_text_or_ocr(page)
            if page_text.strip():
                texts.append(page_text)
    finally:
        doc.close()

    combined = "\n".join(texts).strip()
    if not combined:
        return None

    chunks = chunk_words(combined)
    text_vec = _encode_chunks(chunks)
    if text_vec is None:
        return None

    return {
        "text_vec": text_vec,
        "text_preview": safe_preview(combined, max_chars=150),
    }
