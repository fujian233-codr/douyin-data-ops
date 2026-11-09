"""Pure parsers for values exported by Douyin Creator Center tools."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping


_EMPTY_VALUES = {"", "-", "--", "none", "null", "nan", "未知"}
_NUMBER_WITH_UNIT = re.compile(r"^([+-]?\d+(?:\.\d+)?)\s*(万|亿|w|W)?$")
_VIDEO_URL_ID = re.compile(
    r"(?:douyin\.com/)?(?:video|note)/(\d{6,})",
    re.IGNORECASE,
)


def normalize_header(value: Any) -> str:
    """Normalize a CSV header while preserving Chinese characters."""

    return str(value or "").replace("﻿", "").strip().lower()


def is_empty(value: Any) -> bool:
    if value is None:
        return True
    return normalize_header(value) in _EMPTY_VALUES


def parse_count(value: Any) -> int | None:
    """Parse integer counts, including Chinese units and thousands separators."""

    if is_empty(value):
        return None
    text = str(value).strip().replace(",", "").replace("，", "")
    match = _NUMBER_WITH_UNIT.match(text)
    if not match:
        raise ValueError(f"invalid count: {value!r}")
    number = float(match.group(1))
    unit = match.group(2)
    multiplier = 1
    if unit in {"万", "w", "W"}:
        multiplier = 10_000
    elif unit == "亿":
        multiplier = 100_000_000
    result = number * multiplier
    if result < 0 or int(result) != result:
        raise ValueError(f"invalid count: {value!r}")
    return int(result)


def parse_rate(value: Any) -> float | None:
    """Parse rates into the canonical 0--1 range."""

    if is_empty(value):
        return None
    text = str(value).strip().replace(",", "").replace("，", "")
    percent = text.endswith("%") or text.endswith("％")
    if percent:
        text = text[:-1].strip()
    try:
        number = float(text)
    except ValueError as exc:
        raise ValueError(f"invalid rate: {value!r}") from exc
    if percent:
        number = number / 100
    if number < 0 or number > 1:
        raise ValueError(f"rate out of range: {value!r}")
    return round(number, 8)


def parse_duration_seconds(value: Any) -> int | None:
    """Parse durations such as ``1分03秒``, ``02:41``, and plain seconds."""

    if is_empty(value):
        return None
    text = str(value).strip().lower()

    if re.fullmatch(r"\d{1,2}:\d{2}(?::\d{2})?", text):
        parts = [int(part) for part in text.split(":")]
        if len(parts) == 2:
            minutes, seconds = parts
            return minutes * 60 + seconds
        hours, minutes, seconds = parts
        return hours * 3600 + minutes * 60 + seconds

    match = re.fullmatch(
        r"(?:(\d+)\s*小时)?(?:(\d+)\s*分)?(?:(\d+(?:\.\d+)?)\s*秒)?",
        text,
    )
    if match and any(group is not None for group in match.groups()):
        hours = int(match.group(1) or 0)
        minutes = int(match.group(2) or 0)
        seconds = float(match.group(3) or 0)
        result = hours * 3600 + minutes * 60 + seconds
        return int(result + 0.5)

    try:
        number = float(text)
    except ValueError as exc:
        raise ValueError(f"invalid duration: {value!r}") from exc
    if number < 0:
        raise ValueError(f"invalid duration: {value!r}")
    return int(number + 0.5)


def parse_datetime(value: Any) -> str | None:
    """Normalize common export dates to an ISO-8601 local timestamp."""

    if is_empty(value):
        return None
    text = str(value).strip()
    text = re.sub(r"(\d{4})[年/](\d{1,2})[月/](\d{1,2})日?", r"\1-\2-\3", text)
    text = text.replace("/", "-")
    text = re.sub(r"\s+", " ", text)
    if " " not in text:
        text += " 00:00:00"
    try:
        parsed = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        try:
            parsed = datetime.strptime(text, "%Y-%m-%d %H:%M")
        except ValueError:
            return None
    return parsed.isoformat(timespec="seconds")


def extract_video_id(raw_id: Any, raw_url: Any = "") -> str | None:
    """Return a stable video ID from an ID or Douyin URL."""

    id_text = str(raw_id or "").strip()
    if id_text.isdigit():
        return id_text
    url_text = str(raw_url or "").strip()
    match = _VIDEO_URL_ID.search(url_text)
    if match:
        return match.group(1)
    return None


class FieldMapper:
    """Map varying CSV headers to canonical pipeline fields."""

    def __init__(self, canonical_to_aliases: Mapping[str, Iterable[str]]):
        self._aliases: dict[str, str] = {}
        for canonical, aliases in canonical_to_aliases.items():
            candidates = [canonical, *aliases]
            for alias in candidates:
                normalized = normalize_header(alias)
                if normalized:
                    self._aliases[normalized] = canonical

    @classmethod
    def from_config(cls, path: Path) -> "FieldMapper":
        with path.open("r", encoding="utf-8") as handle:
            return cls(json.load(handle))

    def canonical_headers(self, headers: Iterable[Any]) -> dict[str, str]:
        result: dict[str, str] = {}
        for header in headers:
            canonical = self._aliases.get(normalize_header(header))
            if canonical and canonical not in result:
                result[canonical] = str(header)
        return result

