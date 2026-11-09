"""SQLite persistence for immutable Douyin data snapshots."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable, Iterator, Mapping


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS snapshots (
  snapshot_id TEXT PRIMARY KEY,
  account_label TEXT NOT NULL,
  source_tool TEXT NOT NULL,
  kind TEXT NOT NULL CHECK(kind IN ('works', 'fan_profiles', 'daily_metrics')),
  collected_at TEXT NOT NULL,
  source_file TEXT NOT NULL,
  sha256 TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS works (
  account_label TEXT NOT NULL,
  video_id TEXT NOT NULL,
  title TEXT,
  publish_time TEXT,
  duration_seconds INTEGER,
  status TEXT,
  content_kind TEXT,
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  PRIMARY KEY(account_label, video_id)
);

CREATE TABLE IF NOT EXISTS work_metrics (
  snapshot_id TEXT NOT NULL,
  account_label TEXT NOT NULL,
  video_id TEXT NOT NULL,
  play_count INTEGER,
  exposure_count INTEGER,
  like_count INTEGER,
  comment_count INTEGER,
  share_count INTEGER,
  collect_count INTEGER,
  follower_gain INTEGER,
  homepage_visits INTEGER,
  five_second_completion_rate REAL,
  completion_rate REAL,
  two_second_bounce_rate REAL,
  cover_click_rate REAL,
  average_watch_duration_seconds REAL,
  raw_json TEXT NOT NULL,
  PRIMARY KEY(snapshot_id, video_id),
  FOREIGN KEY(snapshot_id) REFERENCES snapshots(snapshot_id),
  FOREIGN KEY(account_label, video_id)
    REFERENCES works(account_label, video_id)
);

CREATE TABLE IF NOT EXISTS fan_profiles (
  snapshot_id TEXT NOT NULL,
  dimension TEXT NOT NULL,
  segment TEXT NOT NULL,
  value REAL,
  ratio REAL,
  PRIMARY KEY(snapshot_id, dimension, segment),
  FOREIGN KEY(snapshot_id) REFERENCES snapshots(snapshot_id)
);

CREATE TABLE IF NOT EXISTS daily_metrics (
  snapshot_id TEXT NOT NULL,
  stat_date TEXT NOT NULL,
  publish_count INTEGER,
  play_count INTEGER,
  like_count INTEGER,
  share_count INTEGER,
  comment_count INTEGER,
  five_second_completion_rate REAL,
  two_second_bounce_rate REAL,
  cover_click_rate REAL,
  average_watch_duration_seconds REAL,
  total_fans INTEGER,
  follower_net INTEGER,
  follower_gain INTEGER,
  follower_loss INTEGER,
  return_fans INTEGER,
  raw_json TEXT NOT NULL,
  PRIMARY KEY(snapshot_id, stat_date),
  FOREIGN KEY(snapshot_id) REFERENCES snapshots(snapshot_id)
);

CREATE TABLE IF NOT EXISTS import_issues (
  issue_id INTEGER PRIMARY KEY AUTOINCREMENT,
  snapshot_id TEXT NOT NULL,
  row_number INTEGER,
  field_name TEXT,
  issue_type TEXT NOT NULL,
  raw_value TEXT,
  FOREIGN KEY(snapshot_id) REFERENCES snapshots(snapshot_id)
);

CREATE INDEX IF NOT EXISTS idx_snapshots_account_kind_time
  ON snapshots(account_label, kind, collected_at DESC);
CREATE INDEX IF NOT EXISTS idx_work_metrics_snapshot
  ON work_metrics(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_work_metrics_account_video
  ON work_metrics(account_label, video_id);
"""

SNAPSHOT_KINDS = {"works", "fan_profiles", "daily_metrics"}

DAILY_METRIC_COLUMNS = (
    "snapshot_id",
    "stat_date",
    "publish_count",
    "play_count",
    "like_count",
    "share_count",
    "comment_count",
    "five_second_completion_rate",
    "two_second_bounce_rate",
    "cover_click_rate",
    "average_watch_duration_seconds",
    "total_fans",
    "follower_net",
    "follower_gain",
    "follower_loss",
    "return_fans",
    "raw_json",
)


WORK_METRIC_COLUMNS = (
    "snapshot_id",
    "account_label",
    "video_id",
    "play_count",
    "exposure_count",
    "like_count",
    "comment_count",
    "share_count",
    "collect_count",
    "follower_gain",
    "homepage_visits",
    "five_second_completion_rate",
    "completion_rate",
    "two_second_bounce_rate",
    "cover_click_rate",
    "average_watch_duration_seconds",
    "raw_json",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    """Small data-access layer used by the importer and report generator."""

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self.connection
        except Exception:
            self.connection.rollback()
            raise
        else:
            self.connection.commit()

    def create_schema(self) -> None:
        with self.transaction() as connection:
            connection.executescript(SCHEMA)
        self._migrate_snapshot_kind_check()

    def _migrate_snapshot_kind_check(self) -> None:
        """Older databases exclude daily_metrics from the snapshots CHECK."""

        row = self.connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='snapshots'"
        ).fetchone()
        if row is None or "daily_metrics" in str(row["sql"]):
            return
        # Table rebuilds with FK children require the standard
        # foreign_keys=OFF dance; sqlite3 refuses to toggle it mid-transaction.
        self.connection.execute("PRAGMA foreign_keys=OFF")
        with self.transaction() as connection:
            connection.executescript(
                """
                DROP TABLE IF EXISTS snapshots_new;
                CREATE TABLE snapshots_new (
                  snapshot_id TEXT PRIMARY KEY,
                  account_label TEXT NOT NULL,
                  source_tool TEXT NOT NULL,
                  kind TEXT NOT NULL CHECK(kind IN ('works', 'fan_profiles', 'daily_metrics')),
                  collected_at TEXT NOT NULL,
                  source_file TEXT NOT NULL,
                  sha256 TEXT NOT NULL UNIQUE,
                  status TEXT NOT NULL,
                  created_at TEXT NOT NULL
                );
                INSERT INTO snapshots_new
                  SELECT snapshot_id, account_label, source_tool, kind,
                         collected_at, source_file, sha256, status, created_at
                  FROM snapshots;
                DROP TABLE snapshots;
                ALTER TABLE snapshots_new RENAME TO snapshots;
                CREATE INDEX idx_snapshots_account_kind_time
                  ON snapshots(account_label, kind, collected_at DESC);
                """
            )
        self.connection.execute("PRAGMA foreign_keys=ON")

    def snapshot_exists(self, sha256: str) -> bool:
        row = self.connection.execute(
            "SELECT 1 FROM snapshots WHERE sha256=? LIMIT 1", (sha256,)
        ).fetchone()
        return row is not None

    def create_snapshot(
        self,
        *,
        account_label: str,
        source_tool: str,
        collected_at: str,
        source_file: str,
        sha256: str,
        kind: str = "works",
    ) -> str:
        if kind not in SNAPSHOT_KINDS:
            raise ValueError(f"invalid snapshot kind: {kind}")
        if self.snapshot_exists(sha256):
            raise ValueError(f"duplicate snapshot: {sha256}")
        snapshot_id = f"{kind}-{sha256[:20]}"
        with self.transaction() as connection:
            connection.execute(
                """INSERT INTO snapshots(
                       snapshot_id, account_label, source_tool, kind,
                       collected_at, source_file, sha256, status, created_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    snapshot_id,
                    account_label,
                    source_tool,
                    kind,
                    collected_at,
                    str(source_file),
                    sha256,
                    "complete",
                    utc_now(),
                ),
            )
        return snapshot_id

    def latest_snapshot(self, account_label: str, kind: str) -> sqlite3.Row | None:
        return self.connection.execute(
            """SELECT * FROM snapshots
               WHERE account_label=? AND kind=?
               ORDER BY collected_at DESC, created_at DESC, snapshot_id DESC
               LIMIT 1""",
            (account_label, kind),
        ).fetchone()

    def get_snapshot(self, snapshot_id: str) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM snapshots WHERE snapshot_id=?", (snapshot_id,)
        ).fetchone()

    def snapshots_by_kind(
        self, account_label: str, kind: str
    ) -> list[sqlite3.Row]:
        return self.connection.execute(
            """SELECT * FROM snapshots
               WHERE account_label=? AND kind=?
               ORDER BY collected_at DESC, created_at DESC, snapshot_id DESC""",
            (account_label, kind),
        ).fetchall()

    def previous_snapshot(
        self, account_label: str, snapshot_id: str, kind: str = "works"
    ) -> sqlite3.Row | None:
        current = self.get_snapshot(snapshot_id)
        if current is None:
            return None
        return self.connection.execute(
            """SELECT * FROM snapshots
               WHERE account_label=? AND kind=? AND snapshot_id<>?
                 AND collected_at < ?
               ORDER BY collected_at DESC, created_at DESC, snapshot_id DESC
               LIMIT 1""",
            (account_label, kind, snapshot_id, current["collected_at"]),
        ).fetchone()

    def upsert_work(
        self,
        *,
        account_label: str,
        video_id: str,
        title: str | None,
        publish_time: str | None,
        duration_seconds: int | None,
        status: str | None,
        content_kind: str | None,
    ) -> None:
        now = utc_now()
        with self.transaction() as connection:
            connection.execute(
                """INSERT INTO works(
                       account_label, video_id, title, publish_time,
                       duration_seconds, status, content_kind,
                       first_seen_at, last_seen_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(account_label, video_id) DO UPDATE SET
                     title=COALESCE(excluded.title, works.title),
                     publish_time=COALESCE(excluded.publish_time, works.publish_time),
                     duration_seconds=COALESCE(
                       excluded.duration_seconds, works.duration_seconds
                     ),
                     status=COALESCE(excluded.status, works.status),
                     content_kind=COALESCE(excluded.content_kind, works.content_kind),
                     last_seen_at=excluded.last_seen_at""",
                (
                    account_label,
                    video_id,
                    title,
                    publish_time,
                    duration_seconds,
                    status,
                    content_kind,
                    now,
                    now,
                ),
            )

    def insert_work_metric(self, values: Mapping[str, Any]) -> None:
        missing = [column for column in WORK_METRIC_COLUMNS if column not in values]
        if missing:
            raise ValueError(f"missing work metric fields: {', '.join(missing)}")
        columns = ",".join(WORK_METRIC_COLUMNS)
        placeholders = ",".join("?" for _ in WORK_METRIC_COLUMNS)
        with self.transaction() as connection:
            connection.execute(
                f"INSERT INTO work_metrics({columns}) VALUES({placeholders})",
                tuple(values[column] for column in WORK_METRIC_COLUMNS),
            )

    def replace_fan_profiles(
        self, snapshot_id: str, rows: Iterable[Mapping[str, Any]]
    ) -> int:
        materialized = list(rows)
        with self.transaction() as connection:
            connection.execute(
                "DELETE FROM fan_profiles WHERE snapshot_id=?", (snapshot_id,)
            )
            connection.executemany(
                """INSERT INTO fan_profiles(
                       snapshot_id, dimension, segment, value, ratio
                   ) VALUES (?, ?, ?, ?, ?)""",
                [
                    (
                        snapshot_id,
                        row["dimension"],
                        row["segment"],
                        row.get("value"),
                        row.get("ratio"),
                    )
                    for row in materialized
                ],
            )
        return len(materialized)

    def record_issue(
        self,
        *,
        snapshot_id: str,
        row_number: int | None,
        field_name: str | None,
        issue_type: str,
        raw_value: Any,
    ) -> None:
        with self.transaction() as connection:
            connection.execute(
                """INSERT INTO import_issues(
                       snapshot_id, row_number, field_name, issue_type, raw_value
                   ) VALUES (?, ?, ?, ?, ?)""",
                (
                    snapshot_id,
                    row_number,
                    field_name,
                    issue_type,
                    None if raw_value is None else str(raw_value),
                ),
            )

    def work_metrics(self, snapshot_id: str) -> list[sqlite3.Row]:
        return self.connection.execute(
            """SELECT m.*, w.title, w.publish_time, w.duration_seconds,
                      w.status, w.content_kind
               FROM work_metrics AS m
               JOIN works AS w
                 ON w.account_label=m.account_label AND w.video_id=m.video_id
               WHERE m.snapshot_id=?
               ORDER BY w.publish_time DESC, m.video_id DESC""",
            (snapshot_id,),
        ).fetchall()

    def fan_profiles(self, snapshot_id: str) -> list[sqlite3.Row]:
        return self.connection.execute(
            """SELECT dimension, segment, value, ratio
               FROM fan_profiles WHERE snapshot_id=?
               ORDER BY dimension, segment""",
            (snapshot_id,),
        ).fetchall()

    def replace_daily_metrics(
        self, snapshot_id: str, rows: Iterable[Mapping[str, Any]]
    ) -> int:
        materialized = list(rows)
        columns = DAILY_METRIC_COLUMNS
        placeholders = ",".join("?" for _ in columns)
        with self.transaction() as connection:
            connection.execute(
                "DELETE FROM daily_metrics WHERE snapshot_id=?", (snapshot_id,)
            )
            connection.executemany(
                f"INSERT INTO daily_metrics({','.join(columns)}) VALUES({placeholders})",
                [
                    tuple(
                        snapshot_id
                        if column == "snapshot_id"
                        else
                        json.dumps(row.get("raw_json") or {}, ensure_ascii=False)
                        if column == "raw_json"
                        else row.get(column)
                        for column in columns
                    )
                    for row in materialized
                ],
            )
        return len(materialized)

    def daily_metrics_rows(self, account_label: str) -> list[sqlite3.Row]:
        """Latest video + fan daily snapshots merged on stat_date."""

        return self.connection.execute(
            """SELECT v.stat_date AS stat_date,
                      v.play_count, v.like_count, v.share_count, v.comment_count,
                      v.five_second_completion_rate, v.two_second_bounce_rate,
                      v.cover_click_rate, v.average_watch_duration_seconds,
                      f.total_fans, f.follower_net, f.follower_gain,
                      f.follower_loss, f.return_fans
               FROM (
                 SELECT * FROM daily_metrics WHERE snapshot_id = (
                   SELECT s.snapshot_id FROM snapshots s
                   JOIN daily_metrics d ON d.snapshot_id=s.snapshot_id
                   WHERE s.account_label=? AND s.kind='daily_metrics'
                     AND d.play_count IS NOT NULL
                   ORDER BY s.collected_at DESC, s.created_at DESC LIMIT 1
                 )
               ) v
               LEFT JOIN (
                 SELECT * FROM daily_metrics WHERE snapshot_id = (
                   SELECT s.snapshot_id FROM snapshots s
                   JOIN daily_metrics d ON d.snapshot_id=s.snapshot_id
                   WHERE s.account_label=? AND s.kind='daily_metrics'
                     AND d.follower_net IS NOT NULL
                   ORDER BY s.collected_at DESC, s.created_at DESC LIMIT 1
                 )
               ) f ON f.stat_date = v.stat_date
               ORDER BY v.stat_date""",
            (account_label, account_label),
        ).fetchall()

    def issues(self, snapshot_id: str) -> list[sqlite3.Row]:
        return self.connection.execute(
            """SELECT row_number, field_name, issue_type, raw_value
               FROM import_issues WHERE snapshot_id=?
               ORDER BY issue_id""",
            (snapshot_id,),
        ).fetchall()

