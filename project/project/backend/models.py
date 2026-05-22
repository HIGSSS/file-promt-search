"""Singleton-загрузчик ML-моделей.

Модели занимают суммарно ~2–4 ГБ RAM и грузятся 10–30 секунд.
Повторная загрузка при каждом запросе недопустима.

Инициализация — ленивая и защищённая двойной проверкой под блокировкой
(double-checked locking), чтобы одновременный старт двух фоновых задач
не запустил параллельную загрузку одной и той же модели.

Публичные функции:
    get_siglip() -> (model, processor)
    get_sbert() -> SentenceTransformer
    get_ocr() -> PaddleOCR
    warmup() -> None  # принудительная предзагрузка на старте FastAPI
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Optional, Tuple

from config import SBERT_MODEL, SIGLIP_MODEL

logger = logging.getLogger(__name__)

# Единственная блокировка для всех моделей: нагрузка на неё нулевая
# (инициализация происходит один раз), зато код проще.
_lock = threading.Lock()

_siglip: Optional[Tuple[Any, Any]] = None  # (model, processor)
_sbert: Optional[Any] = None
_ocr: Optional[Any] = None


def get_siglip() -> Tuple[Any, Any]:
    """Возвращает (SigLIP model, SigLIP processor). Грузит при первом вызове."""
    global _siglip
    if _siglip is not None:
        return _siglip
    with _lock:
        if _siglip is None:
            logger.info("Загрузка SigLIP: %s", SIGLIP_MODEL)
            # Импорт внутри функции: transformers весит сотни МБ
            # и замедляет импорт backend-модулей при тестах.
            from transformers import AutoModel, AutoProcessor

            model = AutoModel.from_pretrained(SIGLIP_MODEL)
            model.eval()
            processor = AutoProcessor.from_pretrained(SIGLIP_MODEL)
            _siglip = (model, processor)
            logger.info("SigLIP загружен")
    return _siglip


def get_sbert() -> Any:
    """Возвращает SentenceTransformer для многоязычных текстов."""
    global _sbert
    if _sbert is not None:
        return _sbert
    with _lock:
        if _sbert is None:
            logger.info("Загрузка SBERT: %s", SBERT_MODEL)
            from sentence_transformers import SentenceTransformer

            _sbert = SentenceTransformer(SBERT_MODEL)
            logger.info("SBERT загружен")
    return _sbert


def get_ocr() -> Any:
    """Возвращает инициализированный PaddleOCR (русский + английский)."""
    global _ocr
    if _ocr is not None:
        return _ocr
    with _lock:
        if _ocr is None:
            logger.info("Загрузка PaddleOCR")
            from paddleocr import PaddleOCR

            # use_angle_cls=True распознаёт повёрнутые сканы.
            # lang='ru' в PaddleOCR включает и кириллицу, и латиницу.
            _ocr = PaddleOCR(use_angle_cls=True, lang="ru", show_log=False)
            logger.info("PaddleOCR загружен")
    return _ocr


def warmup() -> None:
    """Принудительно прогревает все модели. Вызывается из main.lifespan.

    Без warmup первый запрос к серверу занимает 10–30 секунд из-за
    ленивой инициализации, что ломает UX мобильного клиента.
    """
    get_siglip()
    get_sbert()
    get_ocr()
    logger.info("Все модели прогреты")
