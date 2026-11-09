# Интеллектуальный поиск файлов

Дипломный проект: мобильное приложение семантического поиска файлов
на устройстве с применением машинного обучения.

Реализовано по ТЗ v1.0.

## Структура

```
project/
├── backend/          # FastAPI + PyTorch + FAISS
├── mobile/           # Flutter Android-клиент
└── experiment/       # Датасет и runner для Precision@5
```

## Компоненты

| Часть            | Стек                                                 |
|------------------|------------------------------------------------------|
| Backend          | Python 3.10+, FastAPI, SigLIP, SBERT, PaddleOCR, FAISS |
| Mobile           | Flutter 3.19+, Dart                                  |
| Эксперимент      | Python + requests                                    |

## Быстрый старт

Подробные инструкции — в README каждой подпапки.

```bash
# 1. Запустить backend
cd backend && ./run_server.sh

# 2. Запустить mobile-приложение (в другом терминале)
cd mobile && flutter pub get && flutter run

# 3. Провести эксперимент
cd experiment
python3 generate_dataset.py --out ./test_dataset
# проиндексировать через UI или curl
python3 run_experiment.py --server http://localhost:8000
```

## Улучшения

Перечислены в `backend/README.md`. Основные:

1. **Два отдельных FAISS-индекса** (media 768D + text 384D).
2. **Агрегация по filepath в searcher'е** — без неё формула скоринга `0.6·image + 0.4·text`.
3. **PyMuPDF вместо PyPDF2+pdf2image** — без системного poppler.
4. **Атомарная запись индекса** через `.tmp` + `os.replace` — защита от гонки с `/search`.
5. **Thread-safe `index_state`** с `threading.Lock` + `try_start()` — защита от повторного запуска.
6. **Порог «осмысленного текста»** для PDF — не только длина, но и число слов >2 символов.

## Известные ограничения

Явно указаны в §8 ТЗ:

- Сервер работает на ПК, не на телефоне (модели не уместятся в RAM мобильного устройства)
- Индексация на CPU: ~1–5 сек на файл
- iOS не поддерживается
- Зашифрованные PDF пропускаются
- `.doc` (старый бинарный Word) не поддерживается — только `.docx`
