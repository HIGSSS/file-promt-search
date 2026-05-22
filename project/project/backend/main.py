"""FastAPI-сервер: 3 эндпоинта + lifespan с прогревом моделей.

Запуск:
    uvicorn main:app --host 0.0.0.0 --port 8000

Для adb reverse (USB-подключение телефона):
    adb reverse tcp:8000 tcp:8000
"""
from __future__ import annotations

import logging
import shutil
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

import indexer
import searcher
from config import CURRENT_UPLOAD_DIR, STORAGE_DIR, UPLOADS_DIR
from models import warmup
from schemas import (
    IndexRequest,
    IndexResponse,
    IndexStatus,
    SearchRequest,
    SearchResponse,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Инициализация при старте: директории, модели, ранее построенный индекс."""
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("Прогрев моделей (может занять 10-30 секунд)...")
    warmup()
    # Если индекс уже был построен ранее — подхватываем его, чтобы /search
    # работал сразу после рестарта без переиндексации.
    if searcher.reload():
        logger.info("Индекс подгружен при старте")
    else:
        logger.info("Индекса нет; запустите /index для построения")
    yield
    # Никакой спец. cleanup не нужен: модели GC соберёт при завершении.


app = FastAPI(
    title="Intelligent File Search",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS открыт, т.к. сервер локальный и запускается только во время разработки.
# В продакшене список origin'ов нужно сузить.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/index", response_model=IndexResponse)
async def start_index(req: IndexRequest, background: BackgroundTasks) -> IndexResponse:
    """Запускает фоновую индексацию. Возвращает сразу, не дожидаясь."""
    root = Path(req.path)
    if not root.is_dir():
        raise HTTPException(
            status_code=400,
            detail=f"Директория не найдена: {req.path}",
        )

    # Атомарно переводим состояние в 'indexing'. Если уже идёт — отбиваем.
    if not indexer.try_start():
        return IndexResponse(status="busy", message="Индексация уже идёт")

    # После завершения — перезагружаем индекс в searcher'е, чтобы /search
    # начал возвращать новые результаты без рестарта сервера.
    background.add_task(
        indexer.run_indexing,
        req.path,
        on_finish=searcher.reload,
    )
    return IndexResponse(status="started", message="Индексация запущена")


@app.post("/upload-index", response_model=IndexResponse)
async def upload_and_index(
    background: BackgroundTasks,
    files: list[UploadFile] = File(...),
) -> IndexResponse:
    """Принимает файлы с телефона, сохраняет копии и индексирует их.

    Это основной endpoint для мобильного клиента: Android-пути недоступны
    серверу на ПК, поэтому backend должен работать с локальными копиями.
    """
    if not files:
        raise HTTPException(status_code=400, detail="Файлы не выбраны")

    if not indexer.try_start():
        return IndexResponse(status="busy", message="Индексация уже идёт")

    try:
        if CURRENT_UPLOAD_DIR.exists():
            shutil.rmtree(CURRENT_UPLOAD_DIR)
        CURRENT_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

        saved = 0
        used_names: set[str] = set()
        for i, upload in enumerate(files, start=1):
            filename = _safe_upload_filename(upload.filename, i, used_names)
            target = CURRENT_UPLOAD_DIR / filename
            try:
                with open(target, "wb") as out:
                    while True:
                        chunk = await upload.read(1024 * 1024)
                        if not chunk:
                            break
                        out.write(chunk)
                if target.stat().st_size > 0:
                    saved += 1
                else:
                    target.unlink(missing_ok=True)
            finally:
                await upload.close()

        if saved == 0:
            raise ValueError("Не удалось сохранить ни одного непустого файла")
    except Exception as exc:
        indexer.mark_error(str(exc))
        raise HTTPException(status_code=400, detail=str(exc))

    background.add_task(
        indexer.run_indexing,
        str(CURRENT_UPLOAD_DIR),
        on_finish=searcher.reload,
    )
    return IndexResponse(
        status="started",
        message=f"Загружено файлов: {saved}. Индексация запущена",
    )


@app.post("/index-uploads", response_model=IndexResponse)
async def reindex_uploaded(background: BackgroundTasks) -> IndexResponse:
    """Повторно индексирует последнюю загруженную с телефона выборку."""
    if not CURRENT_UPLOAD_DIR.is_dir() or not any(CURRENT_UPLOAD_DIR.iterdir()):
        raise HTTPException(
            status_code=400,
            detail="Нет загруженных файлов для переиндексации",
        )

    if not indexer.try_start():
        return IndexResponse(status="busy", message="Индексация уже идёт")

    background.add_task(
        indexer.run_indexing,
        str(CURRENT_UPLOAD_DIR),
        on_finish=searcher.reload,
    )
    return IndexResponse(status="started", message="Переиндексация запущена")


@app.get("/status", response_model=IndexStatus)
async def get_status() -> IndexStatus:
    """Текущее состояние индексации. Опрашивается UI каждые 2 секунды."""
    return IndexStatus(**indexer.get_status())


@app.post("/search", response_model=SearchResponse)
async def search_endpoint(req: SearchRequest) -> SearchResponse:
    """Семантический поиск. Требует, чтобы индекс был построен ранее."""
    if not searcher.is_loaded():
        raise HTTPException(
            status_code=400,
            detail="Индекс не найден. Сначала запустите индексацию.",
        )
    try:
        results, elapsed_ms = searcher.measure_search(
            req.query, req.file_type, req.top_k,
        )
    except RuntimeError as exc:
        # Гонка: индекс выгрузили между is_loaded() и search().
        # Маловероятно, но обрабатываем корректно.
        raise HTTPException(status_code=400, detail=str(exc))
    return SearchResponse(results=results, query_time_ms=elapsed_ms)


@app.get("/health")
async def health() -> dict[str, str]:
    """Простой healthcheck для мониторинга и отладки."""
    return {"status": "ok"}


@app.get("/download")
async def download_file(path: str) -> FileResponse:
    """Скачивает файл из upload-хранилища backend'а для открытия на телефоне."""
    try:
        file_path = Path(path).resolve()
        uploads_root = UPLOADS_DIR.resolve()
        if not file_path.is_relative_to(uploads_root):
            raise HTTPException(status_code=403, detail="Файл вне upload-хранилища")
        if not file_path.is_file():
            raise HTTPException(status_code=404, detail="Файл не найден")
        return FileResponse(file_path, filename=file_path.name)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


def _safe_upload_filename(
    raw_name: str | None,
    index: int,
    used_names: set[str],
) -> str:
    """Очищает имя файла от path traversal и конфликтов внутри одной загрузки."""
    name = (raw_name or f"file_{index}").replace("\\", "/").split("/")[-1].strip()
    if not name:
        name = f"file_{index}"

    allowed = []
    for ch in name:
        if ch.isalnum() or ch in " ._-()[]":
            allowed.append(ch)
        else:
            allowed.append("_")
    clean = "".join(allowed).strip(" .")
    if not clean:
        clean = f"file_{index}"

    stem = Path(clean).stem or f"file_{index}"
    suffix = Path(clean).suffix
    candidate = clean
    n = 2
    while candidate.lower() in used_names:
        candidate = f"{stem}_{n}{suffix}"
        n += 1
    used_names.add(candidate.lower())
    return candidate
