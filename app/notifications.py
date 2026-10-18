"""Notification manager storing notifications and printing alerts to the console."""

from datetime import datetime, timezone
import sqlite3
import threading
from typing import Any, Dict, List, Optional


class NotificationManager:
    """Manages publishing and viewing system and workflow notifications."""

    def __init__(self, conn: sqlite3.Connection, lock: threading.Lock) -> None:
        """Initialize with an existing shared SQLite connection and lock."""
        self._conn = conn
        self._lock = lock
        self._init_db()

    def _init_db(self) -> None:
        """Create notifications table if not exists."""
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    recipient_id TEXT NOT NULL,
                    message TEXT NOT NULL,
                    request_id TEXT,
                    notif_type TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_notif_recipient
                ON notifications(recipient_id)
                """
            )
            self._conn.commit()

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def notify(
        self,
        recipient_id: str,
        message: str,
        request_id: str = "",
        notif_type: str = "info",
    ) -> int:
        """Dispatch a notification to console and persist in database.

        Args:
            recipient_id: Target user identifier (e.g. 'alice', 'rita', or 'all_reviewers').
            message: Human-readable notification body.
            request_id: Associated request ID if applicable.
            notif_type: Category ('info', 'approval', 'rejection', 'escalation', 'warning').

        Returns:
            Row ID of the notification.
        """
        now = self._now_iso()

        # Print to console as required by spec (ASCII clean for Windows console)
        print(f"[NOTIFICATION -> {recipient_id.upper()}] [{notif_type.upper()}] {message}")

        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                """
                INSERT INTO notifications (timestamp, recipient_id, message, request_id, notif_type)
                VALUES (?, ?, ?, ?, ?)
                """,
                (now, recipient_id, message, request_id, notif_type),
            )
            self._conn.commit()
            return cursor.lastrowid

    def get_notifications(
        self,
        recipient_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Retrieve recent notifications for a user or across the system."""
        with self._lock:
            cursor = self._conn.cursor()
            if recipient_id:
                cursor.execute(
                    """
                    SELECT id, timestamp, recipient_id, message, request_id, notif_type
                    FROM notifications
                    WHERE recipient_id = ? OR recipient_id = 'all' OR recipient_id = 'all_reviewers'
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (recipient_id, limit),
                )
            else:
                cursor.execute(
                    """
                    SELECT id, timestamp, recipient_id, message, request_id, notif_type
                    FROM notifications
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (limit,),
                )
            return [dict(row) for row in cursor.fetchall()]
