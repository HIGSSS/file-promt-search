"""Процессор табличных файлов: CSV (pandas) и XLSX (openpyxl).

Цель не в том, чтобы проиндексировать все данные, а в том, чтобы
запрос по названиям колонок или характерным значениям нашёл файл.
Поэтому берём только заголовки + первые 50 строк (см. §4.7 ТЗ).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from file_processors.text_processor import encode_text_chunks
from utils import safe_preview

logger = logging.getLogger(__name__)

# Сколько строк данных брать с каждого листа/CSV. Из ТЗ.
TABLE_SAMPLE_ROWS = 50


def process_csv(path: Path) -> Optional[dict[str, Any]]:
    """Читает заголовки + первые 50 строк CSV.

    on_bad_lines='skip' игнорирует строки с неправильным числом колонок.
    Для CSV с нестандартным разделителем pandas сам угадает через engine='python'.
    """
    try:
        import pandas as pd
    except ImportError:
        logger.error("pandas не установлен: pip install pandas")
        return None

    try:
        df = pd.read_csv(
            path,
            nrows=TABLE_SAMPLE_ROWS,
            on_bad_lines="skip",
            sep=None,
            engine="python",
        )
    except Exception as exc:
        logger.warning("Не удалось прочитать CSV %s: %s", path, exc)
        return None

    if df.empty:
        return None

    columns_line = " ".join(str(c) for c in df.columns)
    data_text = df.to_string(index=False)
    combined = f"{columns_line}\n{data_text}"

    text_chunks = encode_text_chunks(combined, label_prefix="csv")
    if not text_chunks:
        return None

    return {
        "text_chunks": text_chunks,
        "text_preview": safe_preview(columns_line, max_chars=150),
    }


def process_xlsx(path: Path) -> Optional[dict[str, Any]]:
    """Обрабатывает все листы XLSX. Читает только чтение + только значения.

    read_only=True + data_only=True важны: без них openpyxl грузит всю
    книгу в память и вычисляет формулы — медленно и затратно по RAM.
    """
    try:
        import openpyxl
    except ImportError:
        logger.error("openpyxl не установлен: pip install openpyxl")
        return None

    try:
        # keep_links=False — не тянуть внешние ссылки.
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True, keep_links=False)
    except Exception as exc:
        logger.warning("Не удалось открыть XLSX %s: %s", path, exc)
        return None

    try:
        parts: list[str] = []
        sheet_names: list[str] = []
        for sheet in wb.worksheets:
            sheet_names.append(sheet.title)
            sheet_lines: list[str] = [f"Лист: {sheet.title}"]
            # iter_rows с max_row=TABLE_SAMPLE_ROWS + 1 = заголовок + данные.
            # values_only=True отдаёт кортежи значений без Cell-обёрток.
            for row in sheet.iter_rows(
                min_row=1, max_row=TABLE_SAMPLE_ROWS + 1, values_only=True
            ):
                # Каждая ячейка → строка; None → пустая строка.
                cells = [str(v) if v is not None else "" for v in row]
                line = " ".join(cells).strip()
                if line:
                    sheet_lines.append(line)
            parts.append("\n".join(sheet_lines))
    finally:
        wb.close()

    combined = "\n\n".join(parts)
    if not combined.strip():
        return None

    text_chunks = encode_text_chunks(combined, label_prefix="xlsx")
    if not text_chunks:
        return None

    preview = "Листы: " + ", ".join(sheet_names)
    return {
        "text_chunks": text_chunks,
        "text_preview": safe_preview(preview, max_chars=150),
    }
