from __future__ import annotations

import re
import unicodedata
from urllib.parse import quote, unquote


_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")
_UNSAFE_FILENAME_CHARS_RE = re.compile(r'["\\;]')


def _sanitize_filename(filename: str) -> str:
    decoded = unquote(filename)
    cleaned = _CONTROL_CHARS_RE.sub("", decoded).replace("\r", "").replace("\n", "")
    cleaned = _UNSAFE_FILENAME_CHARS_RE.sub("", cleaned).strip()
    return cleaned or "download"


def _ascii_fallback(filename: str) -> str:
    normalized = unicodedata.normalize("NFKD", filename).encode("ascii", "ignore").decode("ascii")
    normalized = _UNSAFE_FILENAME_CHARS_RE.sub("", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip(" .")
    return normalized or "download"


def build_attachment_content_disposition(filename: str) -> str:
    safe_filename = _sanitize_filename(filename)
    fallback = _ascii_fallback(safe_filename)
    encoded = quote(safe_filename, safe="")
    return f'attachment; filename="{fallback}"; filename*=UTF-8\'\'{encoded}'
