"""SQLite source of truth for the UAV v0.3 ground application."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .contracts import COMMAND_STATUSES, MISSION_STATUSES, validate_mission_id


DDL = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS missions (
    mission_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    current_epoch INTEGER NOT NULL DEFAULT 0 CHECK(current_epoch >= 0),
    created_at_ns INTEGER NOT NULL,
    updated_at_ns INTEGER NOT NULL,
    manifest_json TEXT NOT NULL DEFAULT '{}',
    failure_reason TEXT
);
CREATE TABLE IF NOT EXISTS mission_epochs (
    mission_id TEXT NOT NULL REFERENCES missions(mission_id),
    capture_epoch INTEGER NOT NULL CHECK(capture_epoch >= 1),
    status TEXT NOT NULL,
    started_at_ns INTEGER NOT NULL,
    ended_at_ns INTEGER,
    manifest_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (mission_id, capture_epoch)
);
CREATE TABLE IF NOT EXISTS commands (
    command_id TEXT PRIMARY KEY,
    command_type TEXT NOT NULL,
    status TEXT NOT NULL,
    operator_session TEXT NOT NULL,
    request_json TEXT NOT NULL,
    response_json TEXT,
    confirmation_json TEXT,
    error_json TEXT,
    created_at_ns INTEGER NOT NULL,
    updated_at_ns INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS command_transitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    command_id TEXT NOT NULL REFERENCES commands(command_id),
    from_status TEXT,
    to_status TEXT NOT NULL,
    detail_json TEXT NOT NULL DEFAULT '{}',
    occurred_at_ns INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS detection_events (
    detection_id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL,
    capture_epoch INTEGER NOT NULL,
    frame_id INTEGER NOT NULL,
    camera_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    received_at_ns INTEGER NOT NULL,
    UNIQUE(mission_id, capture_epoch, frame_id, camera_id, detection_id)
);
CREATE INDEX IF NOT EXISTS detection_identity_idx
ON detection_events(mission_id, capture_epoch, frame_id, camera_id);
CREATE TABLE IF NOT EXISTS imports (
    import_id TEXT PRIMARY KEY,
    mission_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_uri TEXT NOT NULL,
    checksum_sha256 TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    detail_json TEXT NOT NULL DEFAULT '{}',
    created_at_ns INTEGER NOT NULL,
    updated_at_ns INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS reports (
    report_id TEXT PRIMARY KEY,
    detection_id TEXT NOT NULL REFERENCES detection_events(detection_id),
    status TEXT NOT NULL,
    model_identifier TEXT,
    input_json TEXT NOT NULL,
    output_json TEXT,
    dispatch_json TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    next_retry_at_ns INTEGER,
    created_at_ns INTEGER NOT NULL,
    updated_at_ns INTEGER NOT NULL
);
"""


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self.connect() as connection:
            connection.executescript(DDL)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            yield connection
        finally:
            connection.close()

    def create_mission(self, mission_id: str, manifest: dict[str, Any] | None = None) -> dict[str, Any]:
        validate_mission_id(mission_id)
        now = time.time_ns()
        with self._lock, self.connect() as connection:
            connection.execute(
                "INSERT INTO missions(mission_id,status,created_at_ns,updated_at_ns,manifest_json) VALUES(?,?,?,?,?)",
                (mission_id, "CREATED", now, now, json.dumps(manifest or {}, separators=(",", ":"))),
            )
        return self.get_mission(mission_id)

    def get_mission(self, mission_id: str) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM missions WHERE mission_id=?", (mission_id,)).fetchone()
        if row is None:
            raise KeyError(mission_id)
        result = dict(row)
        result["manifest"] = json.loads(result.pop("manifest_json"))
        return result

    def next_epoch(self, mission_id: str) -> int:
        now = time.time_ns()
        with self._lock, self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT current_epoch FROM missions WHERE mission_id=?", (mission_id,)).fetchone()
            if row is None:
                connection.execute("ROLLBACK")
                raise KeyError(mission_id)
            capture_epoch = int(row[0]) + 1
            connection.execute(
                "UPDATE missions SET current_epoch=?, status='RECORDING', updated_at_ns=? WHERE mission_id=?",
                (capture_epoch, now, mission_id),
            )
            connection.execute(
                "INSERT INTO mission_epochs(mission_id,capture_epoch,status,started_at_ns) VALUES(?,?,?,?)",
                (mission_id, capture_epoch, "RECORDING", now),
            )
            connection.execute("COMMIT")
        return capture_epoch

    def set_mission_status(self, mission_id: str, status: str, reason: str | None = None) -> None:
        if status not in MISSION_STATUSES:
            raise ValueError(f"invalid mission status: {status}")
        with self._lock, self.connect() as connection:
            connection.execute(
                "UPDATE missions SET status=?, failure_reason=?, updated_at_ns=? WHERE mission_id=?",
                (status, reason, time.time_ns(), mission_id),
            )

    def insert_detection(self, payload: dict[str, Any]) -> bool:
        with self._lock, self.connect() as connection:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO detection_events(detection_id,mission_id,capture_epoch,frame_id,camera_id,payload_json,received_at_ns) VALUES(?,?,?,?,?,?,?)",
                (
                    payload["detection_id"], payload["mission_id"], payload["capture_epoch"], payload["frame_id"],
                    payload["camera_id"], json.dumps(payload, separators=(",", ":")), time.time_ns(),
                ),
            )
        return cursor.rowcount == 1

    def create_command(self, command_id: str, command_type: str, operator_session: str, request_payload: dict[str, Any]) -> bool:
        now = time.time_ns()
        with self._lock, self.connect() as connection:
            cursor = connection.execute(
                "INSERT OR IGNORE INTO commands(command_id,command_type,status,operator_session,request_json,created_at_ns,updated_at_ns) VALUES(?,?,?,?,?,?,?)",
                (command_id, command_type, "PENDING", operator_session, json.dumps(request_payload), now, now),
            )
            if cursor.rowcount:
                connection.execute(
                    "INSERT INTO command_transitions(command_id,from_status,to_status,occurred_at_ns) VALUES(?,?,?,?)",
                    (command_id, None, "PENDING", now),
                )
        return cursor.rowcount == 1

    def transition_command(self, command_id: str, status: str, detail: dict[str, Any] | None = None) -> None:
        if status not in COMMAND_STATUSES:
            raise ValueError(f"invalid command status: {status}")
        now = time.time_ns()
        with self._lock, self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT status FROM commands WHERE command_id=?", (command_id,)).fetchone()
            if row is None:
                connection.execute("ROLLBACK")
                raise KeyError(command_id)
            connection.execute("UPDATE commands SET status=?,updated_at_ns=? WHERE command_id=?", (status, now, command_id))
            connection.execute(
                "INSERT INTO command_transitions(command_id,from_status,to_status,detail_json,occurred_at_ns) VALUES(?,?,?,?,?)",
                (command_id, row[0], status, json.dumps(detail or {}), now),
            )
            connection.execute("COMMIT")
