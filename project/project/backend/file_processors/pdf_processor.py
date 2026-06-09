"""Процессор PDF: текст через PyMuPDF, сканы и встроенные фото — через EasyOCR.

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
from models import DEVICE, get_ocr, get_siglip
from utils import is_meaningful_text, l2_normalize, safe_preview

logger = logging.getLogger(__name__)

# DPI рендера для OCR. 200 — компромисс скорость/качество: при 150
# мелкий шрифт теряется, при 300 — вдвое медленнее без заметного прироста.
OCR_DPI = 200
VISUAL_PAGES_LIMIT = 6

# Сколько встроенных изображений (фото, скриншоты) максимум прогоняем
# через OCR на весь документ. OCR — самая медленная операция в пайплайне;
# без лимита презентация с полусотней картинок индексировалась бы минутами.
EMBEDDED_IMAGES_LIMIT = 20
# Иконки, буллиты и декоративная графика мельче этого размера — шум для OCR,
# слов в них не бывает, поэтому пропускаем их и экономим время.
EMBEDDED_IMAGE_MIN_SIDE = 80


def _ocr_image(img: Image.Image) -> str:
    reader = get_ocr()
    try:
        results = reader.readtext(np.array(img))
    except Exception as exc:
        logger.warning("OCR упал на изображении: %s", exc)
        return ""
    return " ".join(text for _, text, _ in results if text)


def _ocr_embedded_images(doc: Any, page: Any, budget: list[int]) -> str:
    """Прогоняет OCR по фото/картинкам, встроенным в страницу с текстовым слоем.

    Так слова с фотографий и скриншотов внутри документа попадают в индекс
    наравне с обычным текстом. budget — общий счётчик на весь файл
    (список из одного int, мутируется), чтобы не утонуть в сотнях картинок.
    """
    import fitz

    if budget[0] <= 0:
        return ""
    parts: list[str] = []
    for xref, *_rest in page.get_images(full=True):
        if budget[0] <= 0:
            break
        try:
            pix = fitz.Pixmap(doc, xref)
            if pix.colorspace is None or pix.colorspace.n - pix.alpha > 3:
                pix = fitz.Pixmap(fitz.csRGB, pix)
            if pix.width < EMBEDDED_IMAGE_MIN_SIDE or pix.height < EMBEDDED_IMAGE_MIN_SIDE:
                continue
            img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
        except Exception as exc:
            logger.debug("Не удалось извлечь встроенное изображение xref=%s: %s", xref, exc)
            continue
        budget[0] -= 1
        text = _ocr_image(img)
        if text:
            parts.append(text)
    return " ".join(parts)


def _extract_page_text(page: Any, doc: Any, embedded_budget: list[int]) -> str:
    """Возвращает текст страницы.

    Текстовая страница: текстовый слой + OCR встроенных в неё фото
    (см. _ocr_embedded_images). Скан без текстового слоя: OCR всей
    страницы целиком — фото уже попадут в общий рендер, повторно
    распознавать их по отдельности не нужно.
    """
    native_text = page.get_text() or ""
    if is_meaningful_text(native_text, min_chars=20, min_long_words=3):
        embedded_text = _ocr_embedded_images(doc, page, embedded_budget)
        return f"{native_text}\n{embedded_text}" if embedded_text else native_text

    # Страница — скан. Рендерим в PIL.Image и отдаём OCR.
    try:
        zoom = OCR_DPI / 72.0  # PDF базовый dpi = 72
        pix = page.get_pixmap(matrix=_zoom_matrix(zoom))
        img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
    except Exception as exc:
        logger.warning("Не удалось отрендерить страницу %s: %s", page.number, exc)
        return ""
    return _ocr_image(img)


def _zoom_matrix(zoom: float):
    """Матрица масштабирования для fitz.Page.get_pixmap."""
    import fitz

    return fitz.Matrix(zoom, zoom)


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
        embedded_budget = [EMBEDDED_IMAGES_LIMIT]
        for page in doc:
            if len(page_images) < VISUAL_PAGES_LIMIT:
                page_image = _render_page_image(page)
                if page_image is not None:
                    page_images.append(page_image)
            page_text = _extract_page_text(page, doc, embedded_budget)
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
