"""Процессор изображений: SigLIP для визуального вектора + EasyOCR для текста.

Алгоритм:
    1. Открыть изображение, конвертировать в RGB (SigLIP требует 3 канала).
    2. Получить image_vec через SigLIP.get_image_features.
    3. Прогнать OCR. Если текст > OCR_MIN_CHARS — получить text_vec через SBERT.
    4. Вернуть {'image_vec': ..., 'text_vec': ... | отсутствует, 'text_preview': ...}.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

import numpy as np
import torch
from PIL import Image

from config import OCR_MIN_CHARS
from models import DEVICE, get_ocr, get_sbert, get_siglip
from utils import l2_normalize, safe_preview

logger = logging.getLogger(__name__)


def _encode_image_siglip(image: Image.Image) -> np.ndarray:
    """Получает L2-нормализованный image-вектор SigLIP (dim=768)."""
    model, processor = get_siglip()
    inputs = processor(images=image, return_tensors="pt")
    # Переносим тензоры на то же устройство где лежит модель (CPU или CUDA).
    inputs = {k: v.to(DEVICE) for k, v in inputs.items()}
    with torch.no_grad():
        features = model.get_image_features(**inputs)
    vec = features[0].cpu().numpy()
    return l2_normalize(vec)


def _run_ocr(path: Path) -> str:
    """Прогоняет EasyOCR и возвращает объединённый текст.

    EasyOCR возвращает список (bbox, text, confidence).
    """
    reader = get_ocr()
    try:
        results = reader.readtext(str(path))
    except Exception as exc:
        logger.warning("OCR упал на %s: %s", path, exc)
        return ""
    return " ".join(text for _, text, _ in results if text)


def _encode_text_sbert(text: str) -> np.ndarray:
    """L2-нормализованный SBERT-вектор (dim=384)."""
    sbert = get_sbert()
    vec = sbert.encode(text, convert_to_numpy=True, show_progress_bar=False)
    return l2_normalize(vec)


def process(path: Path) -> Optional[dict[str, Any]]:
    """Обрабатывает изображение. Возвращает dict с векторами или None при ошибке."""
    try:
        # with-блок гарантирует закрытие файла; convert('RGB') нужен
        # для PNG с альфа-каналом и для grayscale.
        with Image.open(path) as img:
            rgb = img.convert("RGB")
            image_vec = _encode_image_siglip(rgb)
    except Exception as exc:
        logger.warning("Не удалось открыть изображение %s: %s", path, exc)
        return None

    result: dict[str, Any] = {"image_vec": image_vec, "text_preview": None}

    ocr_text = _run_ocr(path)
    if len(ocr_text) >= OCR_MIN_CHARS:
        try:
            result["text_vec"] = _encode_text_sbert(ocr_text)
            result["text_preview"] = safe_preview(ocr_text, max_chars=150)
        except Exception as exc:
            logger.warning("SBERT упал на OCR-тексте %s: %s", path, exc)
    return result
