# Backend — Intelligent File Search

FastAPI-сервер: индексация файлов, семантический поиск, гибридный скоринг.

## Требования

- Python 3.10+
- 4+ ГБ свободной RAM (модели SigLIP + SBERT + PaddleOCR)
- ~3 ГБ свободного диска для весов моделей (качаются при первом запуске)

## Быстрый старт

```bash
cd backend
./run_server.sh
# Первый запуск: ставит зависимости, скачивает модели — 10–20 минут.
```

Сервер поднимается на `http://0.0.0.0:8000`.

Альтернатива вручную:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

## Проверка через curl

```bash
# Запуск индексации
curl -X POST http://localhost:8000/index \
    -H "Content-Type: application/json" \
    -d '{"path": "/path/to/folder"}'

# Статус
curl http://localhost:8000/status

# Поиск
curl -X POST http://localhost:8000/search \
    -H "Content-Type: application/json" \
    -d '{"query": "кот у окна", "file_type": "all", "top_k": 10}'
```

## Структура проекта

```
backend/
├── main.py              # FastAPI точка входа, lifespan, эндпоинты
├── config.py            # Пути, размерности, веса скоринга
├── models.py            # Ленивая загрузка SigLIP / SBERT / PaddleOCR
├── indexer.py           # Обход папок, построение FAISS, thread-safe state
├── searcher.py          # Поиск, агрегация по filepath, скоринг
├── schemas.py           # Pydantic-контракт API
├── utils.py             # Нормализация, чанкование
├── file_processors/
│   ├── __init__.py          # Диспетчер по расширению
│   ├── image_processor.py   # SigLIP + PaddleOCR
│   ├── video_processor.py   # 5 кадров → усреднение SigLIP
│   ├── pdf_processor.py     # PyMuPDF + OCR для сканов
│   ├── docx_processor.py    # python-docx
│   ├── text_processor.py    # .txt + fallback на имя файла
│   └── table_processor.py   # CSV / XLSX
└── storage/                 # Создаётся автоматически
    ├── media_index.faiss
    ├── text_index.faiss
    ├── media_metadata.pkl
    └── text_metadata.pkl
```

## Подключение мобильного клиента

Во время разработки подключить Android-устройство и пробросить порт:

```bash
adb reverse tcp:8000 tcp:8000
# В приложении использовать URL http://localhost:8000
```

Для эмулятора Android — `http://10.0.2.2:8000` (localhost хоста со стороны эмулятора).

## Решения и улучшения относительно ТЗ

- **PyMuPDF вместо PyPDF2 + pdf2image.** Одна библиотека, не требует системного poppler.
- **Два отдельных FAISS-индекса** (media 768D + text 384D) вместо одного — нельзя смешать векторы разной размерности в `IndexFlatIP`.
- **Агрегация результатов по filepath в searcher'е** — без неё гибридная формула `0.6·image + 0.4·text` не применима, т.к. FAISS возвращает два вектора как два отдельных hit'а.
- **Атомарная запись индексов** через tmp-файл + `os.replace` — защита от гонки, когда `/search` приходит во время `faiss.write_index`.
- **`threading.Lock` вокруг `index_state`** — защита от рваных чтений `/status` во время фоновой индексации.
- **Порог «осмысленного текста» для определения скан-страниц PDF** — не только длина, но и число слов >2 символов (иначе колонтитул «стр. 5 из 42» считается текстовой страницей).

## Известные ограничения

- Сервер запускается на ПК, не на телефоне. На Android модели не уместятся.
- `.doc` (старый бинарный Word) не поддерживается — только `.docx`.
- Зашифрованные PDF пропускаются без ошибки.
- Индекс типа Flat: точный, но линейный по числу векторов. Для 100k+ файлов стоит перейти на HNSW или IVF.
