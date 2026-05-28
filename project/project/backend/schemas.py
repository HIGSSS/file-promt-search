"""Pydantic-схемы REST API.

Схемы определяют контракт между Flutter-клиентом и FastAPI-сервером.
Изменение любой из них — breaking change для мобильного приложения.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


# --- /index -------------------------------------------------------------
class IndexRequest(BaseModel):
    """Запрос на запуск индексации.

    path должен быть абсолютным и существовать на стороне сервера.
    Валидация существования происходит в эндпоинте, не в схеме, —
    чтобы ответ 400 содержал осмысленное сообщение с конкретным путём.
    """
    path: str = Field(..., min_length=1, description="Абсолютный путь к директории")


class IndexResponse(BaseModel):
    status: Literal["started", "busy"]
    message: str


# --- /status ------------------------------------------------------------
IndexState = Literal["idle", "indexing", "done", "error"]


class IndexStatus(BaseModel):
    """Текущее состояние фоновой индексации.

    Поля processed/total/current_file актуальны только для state == 'indexing'.
    error заполняется только при state == 'error'.
    """
    state: IndexState
    processed: int = 0
    total: int = 0
    current_file: str = ""
    error: Optional[str] = None


# --- /search ------------------------------------------------------------
FileType = Literal["media", "documents", "other", "all"]


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    file_type: FileType = "all"
    top_k: int = Field(20, ge=1, le=1000)
    min_score: float = Field(0.5, ge=0.0, le=1.0)


class SearchResult(BaseModel):
    filepath: str  # путь к backend-копии; mobile открывает его через /download
    filename: str
    type: str  # image | video | pdf | docx | txt | csv | xlsx | other
    score: float
    text_preview: Optional[str] = None


class SearchResponse(BaseModel):
    results: list[SearchResult]
    query_time_ms: int
