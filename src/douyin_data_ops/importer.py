"""Import CSV files exported by DouyinDataReview."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import csv
import hashlib
import json
from pathlib import Path
import re
import shutil
from typing import Any, Iterable, Mapping

from .parsers import (
    FieldMapper,
    extract_video_id,
    is_empty,
    parse_count,
    parse_datetime,
    parse_duration_seconds,
    parse_rate,
)
from .store import Database, utc_now


SOURCE_TOOL = "DouyinDataReview"
COUNT_FIELDS = (
    "play_count",
    "exposure_count",
    "like_count",
    "comment_count",
    "share_count",
    "collect_count",
    "follower_gain",
    "homepage_visits",
)
RATE_FIELDS = (
    "five_second_completion_rate",
    "completion_rate",
    "two_second_bounce_rate",
    "cover_click_rate",
)
WORK_IDENTITY_FIELDS = ("video_id", "video_url")
WORK_INDICATOR_FIELDS = (
    "play_count",
    "like_count",
    "comment_count",
    "share_count",
    "collect_count",
    "completion_rate",
)
FAN_FIELDS = ("dimension", "segment", "value", "ratio")
CORE_WORK_FIELDS = COUNT_FIELDS + RATE_FIELDS + ("average_watch_duration_seconds",)


@dataclass
class ImportSummary:
    source_file: str
    imported: bool
    kind: str | None = None
    snapshot_id: str | None = None
    row_count: int = 0
    issue_count: int = 0
    field_coverage: dict[str, Any] = field(default_factory=dict)
    skip_reason: str | None = None

    @property
    def missing_fields(self) -> list[str]:
        return list(self.field_coverage.get("missing_fields", []))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def collected_time(path: Path) -> str:
    """Use an explicit timestamp in the name, or fall back to file mtime."""

    match = re.search(
        r"(20\d{6})[-_]?(\d{4})",
        path.stem,
    )
    if match:
        date_text, time_text = match.groups()
        parsed = datetime.strptime(f"{date_text}{time_text}", "%Y%m%d%H%M")
        return parsed.isoformat(timespec="seconds")
    return datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")


class DataImporter:
    """Import one or more local CSV exports into SQLite."""

    def __init__(self, root: Path, account_label: str = "main"):
        self.root = root.resolve()
        self.account_label = account_label
        self.database = Database(self.root / "data" / "douyin.db")
        self.database.create_schema()
        self.field_mapper = FieldMapper.from_config(
            self.root / "config" / "field_aliases.json"
        )
        self.raw_directory = self.root / "data" / "raw"
        self.raw_directory.mkdir(parents=True, exist_ok=True)

    def close(self) -> None:
        self.database.close()

    def import_directory(self, inbox: Path) -> list[ImportSummary]:
        path = inbox.resolve()
        if not path.exists():
            return []
        files = sorted(
            candidate
            for candidate in path.iterdir()
            if candidate.is_file() and candidate.suffix.lower() == ".csv"
        )
        return [self.import_file(candidate) for candidate in files]

    def import_file(self, path: Path) -> ImportSummary:
        source = path.resolve()
        if not source.is_file() or source.suffix.lower() != ".csv":
            return ImportSummary(source.name, False, skip_reason="not_csv")

        digest = sha256_file(source)
        if self.database.snapshot_exists(digest):
            return ImportSummary(source.name, False, skip_reason="duplicate_sha256")

        with source.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            headers = reader.fieldnames or []
            canonical_headers = self.field_mapper.canonical_headers(headers)
            rows = list(reader)

        if self._looks_like_works(canonical_headers):
            return self._import_works(source, digest, canonical_headers, rows)
        if self._looks_like_fan_profiles(canonical_headers):
            return self._import_fan_profiles(
                source, digest, canonical_headers, rows
            )
        return ImportSummary(source.name, False, skip_reason="unrecognized_csv")

    @staticmethod
    def _looks_like_works(canonical_headers: Mapping[str, str]) -> bool:
        has_identity = any(field in canonical_headers for field in WORK_IDENTITY_FIELDS)
        has_indicator = any(
            field in canonical_headers for field in WORK_INDICATOR_FIELDS
        )
        return has_identity and has_indicator

    @staticmethod
    def _looks_like_fan_profiles(canonical_headers: Mapping[str, str]) -> bool:
        return all(field in canonical_headers for field in FAN_FIELDS)

    @staticmethod
    def _value(row: Mapping[str, Any], canonical_headers: Mapping[str, str], field: str) -> Any:
        header = canonical_headers.get(field)
        if header is None:
            return None
        return row.get(header)

    def _coverage(self, canonical_headers: Mapping[str, str], kind: str) -> dict[str, Any]:
        fields = CORE_WORK_FIELDS if kind == "works" else FAN_FIELDS
        present = [field for field in fields if field in canonical_headers]
        missing = [field for field in fields if field not in canonical_headers]
        return {
            "present_fields": present,
            "missing_fields": missing,
            "coverage_rate": round(len(present) / len(fields), 4) if fields else 0,
        }

    def _archive(self, source: Path, digest: str) -> Path:
        destination = self.raw_directory / f"{digest}.csv"
        if not destination.exists():
            shutil.copy2(source, destination)
        return destination

    def _import_works(
        self,
        source: Path,
        digest: str,
        canonical_headers: Mapping[str, str],
        rows: Iterable[Mapping[str, Any]],
    ) -> ImportSummary:
        materialized = list(rows)
        parsed_rows: list[dict[str, Any]] = []
        issues: list[dict[str, Any]] = []

        for row_number, row in enumerate(materialized, start=2):
            issue: dict[str, Any] | None = None
            video_id = extract_video_id(
                self._value(row, canonical_headers, "video_id"),
                self._value(row, canonical_headers, "video_url"),
            )
            if not video_id:
                issues.append(
                    {
                        "row_number": row_number,
                        "field_name": "video_id",
                        "issue_type": "missing_video_id",
                        "raw_value": self._value(row, canonical_headers, "video_id"),
                    }
                )
                continue

            metrics: dict[str, Any] = {}
            for field_name in COUNT_FIELDS:
                raw_value = self._value(row, canonical_headers, field_name)
                try:
                    metrics[field_name] = (
                        None if is_empty(raw_value) else parse_count(raw_value)
                    )
                except ValueError:
                    metrics[field_name] = None
                    issues.append(
                        {
                            "row_number": row_number,
                            "field_name": field_name,
                            "issue_type": "invalid_count",
                            "raw_value": raw_value,
                        }
                    )

            for field_name in RATE_FIELDS:
                raw_value = self._value(row, canonical_headers, field_name)
                try:
                    metrics[field_name] = (
                        None if is_empty(raw_value) else parse_rate(raw_value)
                    )
                except ValueError:
                    metrics[field_name] = None
                    issues.append(
                        {
                            "row_number": row_number,
                            "field_name": field_name,
                            "issue_type": "invalid_rate",
                            "raw_value": raw_value,
                        }
                    )

            duration_raw = self._value(
                row, canonical_headers, "average_watch_duration_seconds"
            )
            try:
                average_duration = (
                    None
                    if is_empty(duration_raw)
                    else parse_duration_seconds(duration_raw)
                )
            except ValueError:
                average_duration = None
                issues.append(
                    {
                        "row_number": row_number,
                        "field_name": "average_watch_duration_seconds",
                        "issue_type": "invalid_duration",
                        "raw_value": duration_raw,
                    }
                )

            title = self._value(row, canonical_headers, "title")
            status = self._value(row, canonical_headers, "status")
            content_kind = self._value(row, canonical_headers, "content_kind")
            publish_raw = self._value(row, canonical_headers, "publish_time")
            publish_time = parse_datetime(publish_raw)
            if publish_raw and not publish_time:
                issues.append(
                    {
                        "row_number": row_number,
                        "field_name": "publish_time",
                        "issue_type": "invalid_datetime",
                        "raw_value": publish_raw,
                    }
                )

            parsed_rows.append(
                {
                    "video_id": video_id,
                    "title": None if is_empty(title) else str(title).strip(),
                    "publish_time": publish_time,
                    "status": None if is_empty(status) else str(status).strip(),
                    "content_kind": (
                        None if is_empty(content_kind) else str(content_kind).strip()
                    ),
                    "metrics": metrics,
                    "average_watch_duration_seconds": average_duration,
                    "raw_json": json.dumps(
                        dict(row), ensure_ascii=False, sort_keys=True
                    ),
                }
            )

        if not parsed_rows:
            return ImportSummary(
                source.name,
                False,
                skip_reason="no_valid_work_rows",
                field_coverage=self._coverage(canonical_headers, "works"),
            )

        snapshot_id = self.database.create_snapshot(
            account_label=self.account_label,
            source_tool=SOURCE_TOOL,
            collected_at=collected_time(source),
            source_file=source.name,
            sha256=digest,
            kind="works",
        )
        for item in parsed_rows:
            self.database.upsert_work(
                account_label=self.account_label,
                video_id=item["video_id"],
                title=item["title"],
                publish_time=item["publish_time"],
                duration_seconds=None,
                status=item["status"],
                content_kind=item["content_kind"],
            )
            self.database.insert_work_metric(
                {
                    "snapshot_id": snapshot_id,
                    "account_label": self.account_label,
                    "video_id": item["video_id"],
                    **item["metrics"],
                    "average_watch_duration_seconds": item[
                        "average_watch_duration_seconds"
                    ],
                    "raw_json": item["raw_json"],
                }
            )
        for issue in issues:
            self.database.record_issue(snapshot_id=snapshot_id, **issue)
        self._archive(source, digest)
        coverage = self._coverage(canonical_headers, "works")
        coverage["issue_count"] = len(issues)
        return ImportSummary(
            source.name,
            True,
            "works",
            snapshot_id,
            len(parsed_rows),
            len(issues),
            coverage,
        )

    def _import_fan_profiles(
        self,
        source: Path,
        digest: str,
        canonical_headers: Mapping[str, str],
        rows: Iterable[Mapping[str, Any]],
    ) -> ImportSummary:
        materialized = list(rows)
        parsed_rows: list[dict[str, Any]] = []
        issues: list[dict[str, Any]] = []

        for row_number, row in enumerate(materialized, start=2):
            dimension = self._value(row, canonical_headers, "dimension")
            segment = self._value(row, canonical_headers, "segment")
            if is_empty(dimension) or is_empty(segment):
                issues.append(
                    {
                        "row_number": row_number,
                        "field_name": "dimension" if is_empty(dimension) else "segment",
                        "issue_type": "missing_profile_key",
                        "raw_value": "",
                    }
                )
                continue

            raw_value = self._value(row, canonical_headers, "value")
            raw_ratio = self._value(row, canonical_headers, "ratio")
            value = None
            ratio = None
            try:
                value = None if is_empty(raw_value) else parse_count(raw_value)
            except ValueError:
                issues.append(
                    {
                        "row_number": row_number,
                        "field_name": "value",
                        "issue_type": "invalid_count",
                        "raw_value": raw_value,
                    }
                )
            try:
                ratio = None if is_empty(raw_ratio) else parse_rate(raw_ratio)
            except ValueError:
                issues.append(
                    {
                        "row_number": row_number,
                        "field_name": "ratio",
                        "issue_type": "invalid_rate",
                        "raw_value": raw_ratio,
                    }
                )
            parsed_rows.append(
                {
                    "dimension": str(dimension).strip(),
                    "segment": str(segment).strip(),
                    "value": value,
                    "ratio": ratio,
                }
            )

        if not parsed_rows:
            return ImportSummary(
                source.name,
                False,
                skip_reason="no_valid_fan_rows",
                field_coverage=self._coverage(canonical_headers, "fan_profiles"),
            )

        snapshot_id = self.database.create_snapshot(
            account_label=self.account_label,
            source_tool=SOURCE_TOOL,
            collected_at=collected_time(source),
            source_file=source.name,
            sha256=digest,
            kind="fan_profiles",
        )
        inserted = self.database.replace_fan_profiles(snapshot_id, parsed_rows)
        for issue in issues:
            self.database.record_issue(snapshot_id=snapshot_id, **issue)
        self._archive(source, digest)
        return ImportSummary(
            source.name,
            True,
            "fan_profiles",
            snapshot_id,
            inserted,
            len(issues),
            self._coverage(canonical_headers, "fan_profiles"),
        )

