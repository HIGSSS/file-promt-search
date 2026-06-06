"""Процессор Word-документов через python-docx.

Ограничение: python-docx не читает .doc (бинарный формат Word 97–2003).
Для .doc нужен LibreOffice/antiword — вынесено в направления развития.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from file_processors.text_processor import encode_text_chunks
from utils import safe_preview

logger = logging.getLogger(__name__)


def process(path: Path) -> Optional[dict[str, Any]]:
    """Извлекает текст из .docx и возвращает SBERT-вектор."""
    try:
        import docx  # python-docx
    except ImportError:
        logger.error("python-docx не установлен: pip install python-docx")
        return None

    # .doc (старый бинарный формат) python-docx не откроет — пропускаем.
    if path.suffix.lower() == ".doc":
        logger.info("Пропущен .doc (формат не поддерживается): %s", path)
        return None

    try:
        doc = docx.Document(str(path))
    except Exception as exc:
        logger.warning("Не удалось открыть docx %s: %s", path, exc)
        return None

    lines = [p.text for p in doc.paragraphs if p.text.strip()]

    # Таблицы: важны для учебных работ где условие/данные часто в таблице.
    for table in doc.tables:
        for row in table.rows:
            row_cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if row_cells:
                lines.append(" | ".join(row_cells))

    combined = "\n".join(lines).strip()
    if not combined:
        return None

    text_chunks = encode_text_chunks(combined, label_prefix="docx")
    if not text_chunks:
        return None

    return {
        "text_chunks": text_chunks,
        "text_preview": safe_preview(combined, max_chars=150),
    }
