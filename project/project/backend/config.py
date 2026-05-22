"""Конфигурация backend'а: пути, множества расширений и параметры моделей.

Все переменные окружения считываются один раз на старте.
Отсутствующие директории создаются автоматически в main.lifespan.
"""
from __future__ import annotations

import os
from pathlib import Path

# --- Пути ---------------------------------------------------------------
# BASE_DIR — корень backend'а, независимо от того, откуда запущен сервер.
BASE_DIR: Path = Path(__file__).resolve().parent
STORAGE_DIR: Path = BASE_DIR / "storage"
UPLOADS_DIR: Path = STORAGE_DIR / "uploads"
CURRENT_UPLOAD_DIR: Path = UPLOADS_DIR / "current"

# Два отдельных индекса, т.к. SigLIP и SBERT имеют разные размерности.
MEDIA_INDEX_PATH: Path = STORAGE_DIR / "media_index.faiss"
TEXT_INDEX_PATH: Path = STORAGE_DIR / "text_index.faiss"
MEDIA_META_PATH: Path = STORAGE_DIR / "media_metadata.pkl"
TEXT_META_PATH: Path = STORAGE_DIR / "text_metadata.pkl"

# --- Модели -------------------------------------------------------------
SIGLIP_MODEL: str = os.getenv("SIGLIP_MODEL", "google/siglip-base-patch16-224")
SBERT_MODEL: str = os.getenv("SBERT_MODEL", "paraphrase-multilingual-MiniLM-L12-v2")

# Размерности векторов. Захардкожены намеренно: они определяют
# геометрию FAISS-индексов и не могут измениться от запуска к запуску.
SIGLIP_DIM: int = 768
SBERT_DIM: int = 384

# --- Обработка файлов ---------------------------------------------------
MEDIA_EXTENSIONS: frozenset[str] = frozenset(
    {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".gif"}
)
VIDEO_EXTENSIONS: frozenset[str] = frozenset({".mp4", ".avi", ".mov", ".mkv", ".wmv"})
PDF_EXTENSIONS: frozenset[str] = frozenset({".pdf"})
DOCX_EXTENSIONS: frozenset[str] = frozenset({".docx", ".doc"})
TEXT_EXTENSIONS: frozenset[str] = frozenset({".txt"})
CSV_EXTENSIONS: frozenset[str] = frozenset({".csv"})
TABLE_EXTENSIONS: frozenset[str] = frozenset({".xlsx", ".xls"})

# Видеокадры для усреднения. Больше кадров — стабильнее вектор,
# но линейный рост времени индексации. 5 — компромисс из ТЗ.
VIDEO_FRAMES: int = 5

# Чанкование длинных текстов. Перекрытие 50 слов нужно, чтобы
# границы чанков не разрывали смысловые единицы.
CHUNK_WORDS: int = 400
CHUNK_OVERLAP: int = 50

# Лимит для .txt: большие логи/дампы бессмысленно индексировать целиком.
TEXT_MAX_CHARS: int = 10_000

# Порог длины OCR-текста, ниже которого текстовый вектор не создаётся.
# < 10 символов — это, как правило, шум распознавания.
OCR_MIN_CHARS: int = 10

# --- Скоринг ------------------------------------------------------------
IMAGE_WEIGHT: float = 0.6  # Вес image_sim в комбинированном скоре
TEXT_WEIGHT: float = 0.4   # Вес text_sim в комбинированном скоре
EXACT_MATCH_BONUS: float = 0.05  # Бонус за подстрочное совпадение

# Множитель кандидатов из FAISS. Ищем top_k * CANDIDATE_MULTIPLIER,
# чтобы после агрегации по filepath и фильтрации удалённых файлов
# гарантированно осталось >= top_k результатов.
CANDIDATE_MULTIPLIER: int = 3
