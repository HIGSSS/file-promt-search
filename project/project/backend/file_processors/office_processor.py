"""Lightweight processors for office and text-like formats not covered elsewhere."""
from __future__ import annotations

import re
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Optional
from xml.etree import ElementTree as ET

from file_processors.text_processor import encode_text_chunks
from utils import safe_preview

MAX_TEXT_CHARS = 60_000


def _result_from_text(text: str, label: str) -> Optional[dict[str, Any]]:
    text = " ".join(text.split())
    if not text:
        return None
    text = text[:MAX_TEXT_CHARS]
    chunks = encode_text_chunks(text, label_prefix=label)
    if not chunks:
        return None
    return {
        "text_chunks": chunks,
        "text_preview": safe_preview(text, max_chars=150),
    }


def process_pptx(path: Path) -> Optional[dict[str, Any]]:
    try:
        parts: list[str] = []
        with zipfile.ZipFile(path) as zf:
            slide_names = sorted(
                n for n in zf.namelist()
                if n.startswith("ppt/slides/slide") and n.endswith(".xml")
            )
            for name in slide_names:
                root = ET.fromstring(zf.read(name))
                for node in root.iter():
                    if node.tag.endswith("}t") and node.text:
                        parts.append(node.text)
        return _result_from_text("\n".join(parts), "pptx")
    except Exception:
        return None


def process_odt(path: Path) -> Optional[dict[str, Any]]:
    try:
        with zipfile.ZipFile(path) as zf:
            root = ET.fromstring(zf.read("content.xml"))
        parts = [node.text for node in root.iter() if node.text]
        return _result_from_text("\n".join(parts), "odt")
    except Exception:
        return None


def process_rtf(path: Path) -> Optional[dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    text = re.sub(r"\\'[0-9a-fA-F]{2}", " ", text)
    text = re.sub(r"\\[a-zA-Z]+\d* ?", " ", text)
    text = text.replace("{", " ").replace("}", " ").replace("\\", " ")
    return _result_from_text(text, "rtf")


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data)


def process_plain_text_like(path: Path) -> Optional[dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None

    if path.suffix.lower() in {".html", ".htm"}:
        parser = _HTMLTextExtractor()
        parser.feed(text)
        text = "\n".join(parser.parts)

    return _result_from_text(text, path.suffix.lower().lstrip(".") or "text")
