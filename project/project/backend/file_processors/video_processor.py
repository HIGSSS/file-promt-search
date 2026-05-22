"""Процессор видео: равномерная выборка кадров + усреднение SigLIP-векторов.

Алгоритм:
    1. Открыть видео через cv2.VideoCapture.
    2. Получить total_frames; выбрать VIDEO_FRAMES равномерно распределённых позиций.
    3. Прочитать кадры, конвертировать BGR→RGB→PIL.Image.
    4. Прогнать каждый кадр через SigLIP.
    5. Усреднить векторы и L2-нормализовать.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

import numpy as np
import torch
from PIL import Image

from config import VIDEO_FRAMES
from models import get_siglip
from utils import l2_normalize

logger = logging.getLogger(__name__)


def _extract_frames(path: Path, n_frames: int) -> list[Image.Image]:
    """Читает n_frames равномерно распределённых кадров из видео.

    Использует cv2.CAP_PROP_POS_FRAMES для seek'а. На некоторых кодеках
    seek неточный — но для семантического вектора это не критично.
    """
    # Импорт внутри функции: cv2 стартует медленно и может быть не нужен
    # вообще, если в индексируемой папке нет видео.
    import cv2

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        logger.warning("Не удалось открыть видео: %s", path)
        return []
    try:
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total <= 0:
            return []
        # Равномерная выборка: [total*0/n, total*1/n, ..., total*(n-1)/n].
        # В ТЗ формула именно такая; она гарантирует, что не берётся
        # последний кадр (часто чёрный — артефакт кодека).
        positions = [total * i // n_frames for i in range(n_frames)]
        frames: list[Image.Image] = []
        for pos in positions:
            cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
            ok, frame_bgr = cap.read()
            if not ok or frame_bgr is None:
                continue
            frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            frames.append(Image.fromarray(frame_rgb))
        return frames
    finally:
        cap.release()


def _encode_frames_siglip(frames: list[Image.Image]) -> np.ndarray:
    """Батч-кодирование кадров через SigLIP. Возвращает matrix (N, 768)."""
    model, processor = get_siglip()
    # Батч из N кадров за один forward — быстрее, чем поэлементно.
    inputs = processor(images=frames, return_tensors="pt")
    with torch.no_grad():
        features = model.get_image_features(**inputs)
    return features.cpu().numpy()  # shape: (N, 768)


def process(path: Path) -> Optional[dict[str, Any]]:
    """Обрабатывает видео. Возвращает {'image_vec': ...} или None."""
    frames = _extract_frames(path, VIDEO_FRAMES)
    if not frames:
        logger.warning("Из видео %s не извлечено ни одного кадра", path)
        return None
    try:
        vectors = _encode_frames_siglip(frames)
        # Сначала усредняем, потом нормализуем. Нормализовать каждый
        # кадр и потом усреднять — математически другое: усреднение
        # сохраняет направления, где кадры согласованы, и подавляет шум.
        mean_vec = np.mean(vectors, axis=0)
        return {
            "image_vec": l2_normalize(mean_vec),
            "text_preview": None,
        }
    except Exception as exc:
        logger.warning("Ошибка кодирования видео %s: %s", path, exc)
        return None
