"""Agent audit log persistence for full workflow observability.

Records every agent interaction, tool invocation, latency measurement,
token expenditure, failure, and security event.
"""

from datetime import datetime, timezone
import json
import sqlite3
import threading
from typing import Any, Dict, List, Optional


class AuditLogger:
    """Manages recording and retrieval of audit events in SQLite."""

    def __init__(self, conn: sqlite3.Connection, lock: threading.Lock) -> None:
        """Initialize with an existing shared connection and thread lock.

        Args:
            conn: SQLite connection shared with service/orchestrator.
            lock: Thread lock ensuring synchronized writes.
        """
        self._conn = conn
        self._lock = lock
        self._init_db()

    def _init_db(self) -> None:
        """Create audit log schema if not present."""
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    request_id TEXT,
                    actor_id TEXT NOT NULL,
                    actor_role TEXT NOT NULL,
                    agent TEXT NOT NULL,
                    input TEXT NOT NULL,
                    output TEXT NOT NULL,
                    reason TEXT,
                    status TEXT NOT NULL,
                    latency_s REAL NOT NULL,
                    tokens_in INTEGER NOT NULL,
                    tokens_out INTEGER NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_audit_request_id
                ON agent_audit_log(request_id)
                """
            )
            self._conn.commit()

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def log_event(
        self,
        actor_id: str,
        actor_role: str,
        agent: str,
        input_data: Any,
        output_data: Any,
        status: str,
        request_id: Optional[str] = None,
        reason: Optional[str] = None,
        latency_s: float = 0.0,
        tokens_in: int = 0,
        tokens_out: int = 0,
    ) -> int:
        """Persist a single audit record.

        Returns:
            Row ID of the inserted record.
        """
        now = self._now_iso()
        in_str = input_data if isinstance(input_data, str) else json.dumps(input_data, default=str)
        out_str = output_data if isinstance(output_data, str) else json.dumps(output_data, default=str)

        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                """
                INSERT INTO agent_audit_log (
                    timestamp, request_id, actor_id, actor_role, agent,
                    input, output, reason, status, latency_s, tokens_in, tokens_out
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    now,
                    request_id,
                    actor_id,
                    actor_role,
                    agent,
                    in_str,
                    out_str,
                    reason or "",
                    status,
                    float(latency_s),
                    int(tokens_in),
                    int(tokens_out),
                ),
            )
            self._conn.commit()
            return cursor.lastrowid

    def get_logs(
        self,
        request_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Retrieve audit logs optionally filtered by request_id."""
        with self._lock:
            cursor = self._conn.cursor()
            if request_id:
                cursor.execute(
                    """
                    SELECT id, timestamp, request_id, actor_id, actor_role, agent,
                           input, output, reason, status, latency_s, tokens_in, tokens_out
                    FROM agent_audit_log
                    WHERE request_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (request_id, limit),
                )
            else:
                cursor.execute(
                    """
                    SELECT id, timestamp, request_id, actor_id, actor_role, agent,
                           input, output, reason, status, latency_s, tokens_in, tokens_out
                    FROM agent_audit_log
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (limit,),
                )
            return [dict(row) for row in cursor.fetchall()]
