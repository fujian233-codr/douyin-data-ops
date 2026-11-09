"""Minimal read-only XLSX support built on the standard library.

Douyin Creator Center exports simple wide tables (one header row, shared
strings, no formulas), so a small ``zipfile`` + ``ElementTree`` reader is
enough and the project stays dependency-free.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any


_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_CELL_REF = re.compile(r"([A-Z]+)")


def _column_index(letters: str) -> int:
    result = 0
    for char in letters:
        result = result * 26 + (ord(char) - ord("A") + 1)
    return result - 1


def _sheet_paths(archive: zipfile.ZipFile) -> list[str]:
    return sorted(
        name
        for name in archive.namelist()
        if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name)
    )


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    values: list[str] = []
    for item in root.findall(f"{{{_NS}}}si"):
        values.append("".join(node.text or "" for node in item.iter(f"{{{_NS}}}t")))
    return values


def _cell_value(cell: ET.Element, shared: list[str]) -> str:
    kind = cell.attrib.get("t")
    if kind == "inlineStr":
        inline = cell.find(f"{{{_NS}}}is")
        if inline is None:
            return ""
        return "".join(node.text or "" for node in inline.iter(f"{{{_NS}}}t"))
    raw = cell.find(f"{{{_NS}}}v")
    if raw is None or raw.text is None:
        return ""
    if kind == "s":
        try:
            return shared[int(raw.text)]
        except (ValueError, IndexError):
            return ""
    return raw.text


def read_sheet_rows(path: Path) -> list[dict[str, str]]:
    """Read the first worksheet as ``{header: value}`` dicts."""

    try:
        with zipfile.ZipFile(path) as archive:
            sheets = _sheet_paths(archive)
            if not sheets:
                raise ValueError("workbook has no worksheets")
            shared = _shared_strings(archive)
            root = ET.fromstring(archive.read(sheets[0]))
    except (zipfile.BadZipFile, ET.ParseError) as error:
        raise ValueError(f"invalid xlsx file: {path.name}") from error

    table: list[list[str]] = []
    for row in root.iter(f"{{{_NS}}}row"):
        cells: dict[int, str] = {}
        for cell in row.findall(f"{{{_NS}}}c"):
            ref = cell.attrib.get("r", "")
            match = _CELL_REF.match(ref)
            index = _column_index(match.group(1)) if match else len(cells)
            cells[index] = _cell_value(cell, shared)
        if cells:
            width = max(cells) + 1
            table.append([cells.get(index, "") for index in range(width)])
    if not table:
        return []

    headers = [value.strip() for value in table[0]]
    rows: list[dict[str, str]] = []
    for values in table[1:]:
        row: dict[str, str] = {}
        for index, header in enumerate(headers):
            if header:
                row[header] = values[index] if index < len(values) else ""
        rows.append(row)
    return rows


# ---- Douyin daily metric files -------------------------------------------

VIDEO_HEADER_MAP: dict[str, str] = {
    "日期": "stat_date",
    "投稿量": "publish_count",
    "总播放量": "play_count",
    "总点赞量": "like_count",
    "总分享量": "share_count",
    "总评论量": "comment_count",
    "5秒完播率": "five_second_completion_rate",
    "2秒跳出率": "two_second_bounce_rate",
    "封面点击率": "cover_click_rate",
    "平均播放时长": "average_watch_duration_seconds",
}

FAN_HEADER_MAP: dict[str, str] = {
    "日期": "stat_date",
    "总粉丝量": "total_fans",
    "粉丝净增": "follower_net",
    "吸粉量": "follower_gain",
    "脱粉量": "follower_loss",
    "回访粉丝量": "return_fans",
}

VIDEO_DAILY_FIELDS = (
    "play_count",
    "like_count",
    "share_count",
    "comment_count",
    "five_second_completion_rate",
    "two_second_bounce_rate",
    "cover_click_rate",
    "average_watch_duration_seconds",
)

FAN_DAILY_FIELDS = (
    "total_fans",
    "follower_net",
    "follower_gain",
    "follower_loss",
    "return_fans",
)

_SECONDS_WITH_SUFFIX = re.compile(r"^(-?\d+(?:\.\d+)?)\s*s$", re.IGNORECASE)
_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _is_empty(value: Any) -> bool:
    return value is None or str(value).strip() in {"", "-", "--"}


def _int(value: Any, *, signed: bool = False) -> int | None:
    if _is_empty(value):
        return None
    text = str(value).strip().replace(",", "").replace("，", "")
    try:
        number = float(text)
    except ValueError:
        return None
    if not signed and number < 0:
        return None
    return int(number)


def _rate(value: Any) -> float | None:
    if _is_empty(value):
        return None
    text = str(value).strip().replace(",", "").replace("，", "")
    if text.endswith(("%", "％")):
        text = text[:-1]
    try:
        number = float(text)
    except ValueError:
        return None
    return number / 100 if number > 1 else number


def _seconds(value: Any) -> float | None:
    if _is_empty(value):
        return None
    text = str(value).strip()
    match = _SECONDS_WITH_SUFFIX.match(text)
    if match:
        return float(match.group(1))
    if re.fullmatch(r"-?\d+(?:\.\d+)?", text):
        return float(text)
    return None


def detect_daily_kind(rows: list[dict[str, str]]) -> str | None:
    """Return 'video' / 'fan' by matching known Douyin export headers."""

    if not rows:
        return None
    headers = set(rows[0])
    if {"总播放量", "5秒完播率"} & headers:
        return "video"
    if {"粉丝净增", "吸粉量", "总粉丝量"} & headers:
        return "fan"
    return None


def parse_daily_rows(
    rows: list[dict[str, str]],
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    """Parse one daily file into canonical rows; returns (kind, rows, issues)."""

    kind = detect_daily_kind(rows)
    if kind is None:
        return "", [], [{"issue_type": "unrecognized_daily_layout"}]
    header_map = VIDEO_HEADER_MAP if kind == "video" else FAN_HEADER_MAP

    parsed: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    for row_number, row in enumerate(rows, start=2):
        canonical = {
            header_map[name]: value
            for name, value in row.items()
            if name in header_map
        }
        date_text = str(canonical.get("stat_date", "")).strip()
        if not _ISO_DATE.match(date_text):
            issues.append(
                {
                    "row_number": row_number,
                    "field_name": "stat_date",
                    "issue_type": "invalid_date",
                    "raw_value": canonical.get("stat_date"),
                }
            )
            continue

        result: dict[str, Any] = {"stat_date": date_text}
        for field, value in canonical.items():
            if field == "stat_date":
                continue
            if field == "average_watch_duration_seconds":
                result[field] = _seconds(value)
            elif field.endswith("_rate"):
                result[field] = _rate(value)
            else:
                result[field] = _int(value, signed=field == "follower_net")
        result["raw_json"] = {
            name: value for name, value in row.items() if name not in header_map
        }
        parsed.append(result)
    return kind, parsed, issues
