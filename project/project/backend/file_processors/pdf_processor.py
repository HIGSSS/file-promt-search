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
import torch

from file_processors.text_processor import encode_text_chunks
from models import DEVICE, get_ocr, get_sbert, get_siglip
from utils import chunk_words, is_meaningful_text, l2_normalize, safe_preview

logger = logging.getLogger(__name__)

# DPI рендера для OCR. 200 — компромисс скорость/качество: при 150
# мелкий шрифт теряется, при 300 — вдвое медленнее без заметного прироста.
OCR_DPI = 200
VISUAL_PAGES_LIMIT = 6


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

    reader = get_ocr()
    try:
        results = reader.readtext(np.array(img))
    except Exception as exc:
        logger.warning("OCR упал на странице %s: %s", page.number, exc)
        return ""
    return " ".join(text for _, text, _ in results if text)


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


def _encode_images_siglip(images: list[Image.Image]) -> Optional[np.ndarray]:
    """Encodes rendered PDF pages as visual content for scanned/illustrated PDFs."""
    if not images:
        return None
    model, processor = get_siglip()
    inputs = processor(images=images, return_tensors="pt")
    inputs = {k: v.to(DEVICE) for k, v in inputs.items()}
    with torch.no_grad():
        features = model.get_image_features(**inputs)
    return l2_normalize(np.mean(features.cpu().numpy(), axis=0))


def _render_page_image(page: Any, dpi: int = 144) -> Optional[Image.Image]:
    try:
        zoom = dpi / 72.0
        pix = page.get_pixmap(matrix=_zoom_matrix(zoom))
        return Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
    except Exception as exc:
        logger.warning("Не удалось отрендерить PDF-страницу %s: %s", page.number, exc)
        return None


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
        page_images: list[Image.Image] = []
        for page in doc:
            if len(page_images) < VISUAL_PAGES_LIMIT:
                page_image = _render_page_image(page)
                if page_image is not None:
                    page_images.append(page_image)
            page_text = _extract_page_text_or_ocr(page)
            if page_text.strip():
                texts.append(page_text)
    finally:
        doc.close()

    combined = "\n".join(texts).strip()
    image_vec = _encode_images_siglip(page_images)
    if not combined and image_vec is None:
        return None

    text_chunks = encode_text_chunks(combined, label_prefix="pdf") if combined else []

    result: dict[str, Any] = {
        "text_preview": safe_preview(combined, max_chars=150) if combined else None,
    }
    if image_vec is not None:
        result["image_vec"] = image_vec
    if text_chunks:
        result["text_chunks"] = text_chunks
    return result
