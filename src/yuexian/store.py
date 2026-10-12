"""与「以后接数据库」对应的表和写入方式。

使用标准库 SQLite，只为把表结构跑通。申报演示、规则判定和压舱
仍读 data/shipments.json，不会调用本模块。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

RULE_VERSION = "track2-2026-10"

SCHEMA = """
CREATE TABLE IF NOT EXISTS shipment (
    id TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS document (
    id INTEGER PRIMARY KEY,
    shipment_id TEXT NOT NULL,
    doc_type TEXT NOT NULL,
    checksum TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    dispatch_rule TEXT NOT NULL,
    FOREIGN KEY (shipment_id) REFERENCES shipment(id)
);

CREATE TABLE IF NOT EXISTS observation (
    id INTEGER PRIMARY KEY,
    shipment_id TEXT NOT NULL,
    document_id INTEGER,
    field TEXT NOT NULL,
    station TEXT,
    value TEXT,
    label TEXT NOT NULL,
    FOREIGN KEY (shipment_id) REFERENCES shipment(id),
    FOREIGN KEY (document_id) REFERENCES document(id)
);

CREATE TABLE IF NOT EXISTS judgement (
    id INTEGER PRIMARY KEY,
    shipment_id TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    threshold REAL NOT NULL,
    verdict TEXT NOT NULL,
    headline TEXT NOT NULL,
    detail TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (shipment_id) REFERENCES shipment(id)
);

CREATE TABLE IF NOT EXISTS job (
    id INTEGER PRIMARY KEY,
    shipment_id TEXT NOT NULL,
    status TEXT NOT NULL,
    fallback_reason TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (shipment_id) REFERENCES shipment(id)
);
"""


def connect(path: str | Path = ":memory:") -> sqlite3.Connection:
    database = sqlite3.connect(path)
    database.row_factory = sqlite3.Row
    database.execute("PRAGMA foreign_keys = ON")
    database.executescript(SCHEMA)
    return database


def ensure_shipment(database: sqlite3.Connection, shipment_id: str) -> None:
    database.execute("INSERT OR IGNORE INTO shipment (id) VALUES (?)", (shipment_id,))


def add_document(
    database: sqlite3.Connection,
    shipment_id: str,
    doc_type: str,
    storage_path: str,
    dispatch_rule: str,
    body: bytes | None = None,
) -> int:
    """库里只留类型、校验和、位置和调度路径。正文留在调用方给出的路径。"""
    ensure_shipment(database, shipment_id)
    checksum = hashlib.sha256(body or storage_path.encode("utf-8")).hexdigest()
    cursor = database.execute(
        """
        INSERT INTO document (shipment_id, doc_type, checksum, storage_path, dispatch_rule)
        VALUES (?, ?, ?, ?, ?)
        """,
        (shipment_id, doc_type, checksum, storage_path, dispatch_rule),
    )
    database.commit()
    return int(cursor.lastrowid)


def add_observations(
    database: sqlite3.Connection,
    shipment_id: str,
    observations: list[dict],
    document_id: int | None = None,
) -> None:
    ensure_shipment(database, shipment_id)
    database.executemany(
        """
        INSERT INTO observation (shipment_id, document_id, field, station, value, label)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (
                shipment_id,
                document_id,
                item["field"],
                item.get("station"),
                None if item.get("value") is None else str(item["value"]),
                item.get("label") or "rewrite",
            )
            for item in observations
        ],
    )
    database.commit()


def append_judgement(
    database: sqlite3.Connection,
    judged: dict,
    threshold: float,
    rule_version: str = RULE_VERSION,
) -> int:
    """只插入新结论。同一票可以有多条，整改不覆盖上一次。"""
    shipment_id = str(judged["id"])
    ensure_shipment(database, shipment_id)
    cursor = database.execute(
        """
        INSERT INTO judgement (
            shipment_id, rule_version, threshold, verdict, headline, detail, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            shipment_id,
            rule_version,
            threshold,
            judged["verdict"],
            judged["headline"],
            json.dumps(
                {"blocks": judged.get("blocks", []), "pending": judged.get("pending", [])},
                ensure_ascii=False,
            ),
            _now(),
        ),
    )
    database.commit()
    return int(cursor.lastrowid)


def judgement_history(database: sqlite3.Connection, shipment_id: str) -> list[dict]:
    rows = database.execute(
        """
        SELECT id, rule_version, threshold, verdict, headline, detail, created_at
        FROM judgement WHERE shipment_id = ? ORDER BY id
        """,
        (shipment_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def enqueue_job(database: sqlite3.Connection, shipment_id: str) -> int:
    ensure_shipment(database, shipment_id)
    cursor = database.execute(
        "INSERT INTO job (shipment_id, status, fallback_reason, created_at) VALUES (?, 'pending', NULL, ?)",
        (shipment_id, _now()),
    )
    database.commit()
    return int(cursor.lastrowid)


def finish_job(database: sqlite3.Connection, job_id: int, status: str, fallback_reason: str | None = None) -> None:
    if status not in {"running", "done", "fallback"}:
        raise ValueError(f"不支持的任务状态：{status}")
    database.execute(
        "UPDATE job SET status = ?, fallback_reason = ? WHERE id = ?",
        (status, fallback_reason, job_id),
    )
    database.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
