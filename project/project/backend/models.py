"""Singleton-загрузчик ML-моделей.

Модели занимают суммарно ~2–4 ГБ RAM и грузятся 10–30 секунд.
Повторная загрузка при каждом запросе недопустима.

Инициализация — ленивая и защищённая двойной проверкой под блокировкой
(double-checked locking), чтобы одновременный старт двух фоновых задач
не запустил параллельную загрузку одной и той же модели.

Публичные функции:
    get_siglip() -> (model, processor)
    get_sbert() -> SentenceTransformer
    get_ocr() -> EasyOCR
    warmup() -> None  # принудительная предзагрузка на старте FastAPI
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Optional, Tuple

import torch

from config import SBERT_MODEL, SIGLIP_MODEL

logger = logging.getLogger(__name__)


def _detect_device() -> torch.device:
    """Проверяет CUDA реальным запуском ядра; при любой ошибке возвращает CPU.

    torch.cuda.is_available() проверяет только наличие драйвера, но НЕ
    совместимость compute capability. «no kernel image» возникает позже —
    при первом запуске ядра. Поэтому тест с реальным тензором обязателен.
    """
    if not torch.cuda.is_available():
        logger.info("CUDA недоступна — используем CPU")
        return torch.device("cpu")
    try:
        t = torch.tensor([1.0], device="cuda")
        _ = t + t          # форсируем запуск CUDA-ядра
        del t
        cc = torch.cuda.get_device_capability()
        name = torch.cuda.get_device_name(0)
        logger.info("GPU: %s (compute capability %d.%d)", name, cc[0], cc[1])
        return torch.device("cuda")
    except Exception as exc:
        logger.warning(
            "GPU обнаружен, но CUDA-ядра не запустились (%s). "
            "Вероятно, PyTorch скомпилирован для другой версии CUDA. "
            "Запустите: nvidia-smi (посмотрите версию CUDA), затем переустановите "
            "PyTorch с нужной версией: pip install torch --index-url "
            "https://download.pytorch.org/whl/cu<VERSION>. Используем CPU.",
            exc,
        )
        return torch.device("cpu")


# Определяем устройство один раз при старте. Все модели и тензоры
# переводятся на это же устройство в своих функциях.
DEVICE: torch.device = _detect_device()

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
            logger.info("Загрузка SigLIP: %s (устройство: %s)", SIGLIP_MODEL, DEVICE)
            from transformers import AutoModel, AutoProcessor

            model = AutoModel.from_pretrained(SIGLIP_MODEL)
            model.eval()
            model = model.to(DEVICE)
            processor = AutoProcessor.from_pretrained(SIGLIP_MODEL)
            _siglip = (model, processor)
            logger.info("SigLIP загружен на %s", DEVICE)
    return _siglip


def get_sbert() -> Any:
    """Возвращает SentenceTransformer для многоязычных текстов."""
    global _sbert
    if _sbert is not None:
        return _sbert
    with _lock:
        if _sbert is None:
            logger.info("Загрузка SBERT: %s (устройство: %s)", SBERT_MODEL, DEVICE)
            from sentence_transformers import SentenceTransformer

            # sentence_transformers принимает строку 'cuda'/'cpu'.
            _sbert = SentenceTransformer(SBERT_MODEL, device=str(DEVICE))
            logger.info("SBERT загружен на %s", DEVICE)
    return _sbert


_translator: Optional[Any] = None


_translator_failed = False  # True если загрузка провалилась — не пытаемся снова


def get_translator() -> Optional[Any]:
    """Возвращает Helsinki ru→en переводчик или None если не установлен."""
    global _translator, _translator_failed
    if _translator is not None:
        return _translator
    if _translator_failed:
        return None
    with _lock:
        if _translator is None and not _translator_failed:
            try:
                logger.info("Загрузка переводчика Helsinki-NLP/opus-mt-ru-en")
                from transformers import pipeline
                _translator = pipeline(
                    "translation",
                    model="Helsinki-NLP/opus-mt-ru-en",
                    device=0 if DEVICE.type == "cuda" else -1,
                )
                logger.info("Переводчик загружен — поиск фото на русском улучшен")
            except Exception as exc:
                _translator_failed = True
                logger.warning(
                    "Переводчик не загружен (%s). "
                    "Установите: pip install sentencepiece sacremoses "
                    "и перезапустите сервер. "
                    "Пока поиск фото работает на оригинальном языке запроса.", exc,
                )
    return _translator


def translate_to_english(text: str) -> str:
    """Переводит запрос на английский для лучшей совместимости с SigLIP."""
    translator = get_translator()
    if translator is None:
        return text
    try:
        result = translator(text, max_length=512)
        translated = result[0]["translation_text"]
        logger.info("SigLIP: '%s' → '%s'", text, translated)
        return translated
    except Exception as exc:
        logger.warning("Перевод не удался (%s) — оригинал: '%s'", exc, text)
        return text


def get_ocr() -> Any:
    """Возвращает инициализированный EasyOCR (русский + английский)."""
    global _ocr
    if _ocr is not None:
        return _ocr
    with _lock:
        if _ocr is None:
            logger.info("Загрузка EasyOCR (ru+en, GPU=%s)", DEVICE.type == "cuda")
            import easyocr
            # EasyOCR работает поверх PyTorch — нет конфликта oneDNN как у PaddleOCR.
            _ocr = easyocr.Reader(
                ["ru", "en"],
                gpu=DEVICE.type == "cuda",
                verbose=False,
            )
            logger.info("EasyOCR загружен")
    return _ocr


def warmup() -> None:
    """Принудительно прогревает все модели. Вызывается из main.lifespan.

    Без warmup первый запрос к серверу занимает 10–30 секунд из-за
    ленивой инициализации, что ломает UX мобильного клиента.
    """
    get_siglip()
    get_sbert()
    get_ocr()
    # Переводчик НЕ прогреваем здесь: Helsinki-NLP/opus-mt-ru-en — это ещё
    # одна модель в сотни МБ, которая нужна только для медиа-поиска на русском.
    # Прогрев добавлял заметное время к каждому старту сервера, даже когда
    # пользователь вообще не ищет фото по-русски. Загружается лениво при
    # первом таком запросе (см. translate_to_english).
    logger.info("Все модели прогреты")
