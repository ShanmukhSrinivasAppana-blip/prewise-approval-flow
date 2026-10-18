"""Request service managing lifecycle, persistence, and state transitions.

The deterministic backend decides:
- All status transitions pass through `transition_request`.
- Centralized validation enforces strict ordering:
  1. Unknown action -> UNKNOWN_ACTION
  2. Not found -> NOT_FOUND
  3. Role check -> ROLE_NOT_ALLOWED
  4. Ownership check -> NOT_OWNER
  5. Allowed from-status -> INVALID_TRANSITION
- Atomic SQLite updates guarantee race-condition safety.
- Reviewers cannot see Draft requests.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import sqlite3
import threading
from typing import Any, Dict, List, Optional
import uuid

from app.rules import (
    MAX_DESCRIPTION_LENGTH,
    MAX_TITLE_LENGTH,
    RULES,
    Role,
    Status,
)


class ErrorCode(str, Enum):
    """Canonical error codes returned by the service layer."""
    ROLE_NOT_ALLOWED = "ROLE_NOT_ALLOWED"
    NOT_OWNER = "NOT_OWNER"
    INVALID_TRANSITION = "INVALID_TRANSITION"
    NOT_FOUND = "NOT_FOUND"
    NOT_VISIBLE = "NOT_VISIBLE"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    UNKNOWN_ACTION = "UNKNOWN_ACTION"
    CONFLICT = "CONFLICT"


@dataclass(frozen=True)
class User:
    """Immutable user representation identifying the actor in all operations."""
    id: str
    role: Role
    name: str = ""


class RequestService:
    """SQLite-backed deterministic service for managing request approvals."""

    def __init__(self, db_path: str = ":memory:") -> None:
        """Initialize the database connection and schema.

        Args:
            db_path: Path to SQLite database file or ':memory:' for tests.
        """
        self.db_path = db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        """Create required tables and indexes if they do not exist."""
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS requests (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    status TEXT NOT NULL,
                    creator_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS request_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    from_status TEXT NOT NULL,
                    to_status TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    actor_role TEXT NOT NULL,
                    reason TEXT,
                    timestamp TEXT NOT NULL,
                    FOREIGN KEY (request_id) REFERENCES requests(id)
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_requests_status
                ON requests(status)
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_history_request_id
                ON request_history(request_id)
                """
            )
            self._conn.commit()

    @staticmethod
    def _now_iso() -> str:
        """Return current UTC time in ISO-8601 format."""
        return datetime.now(timezone.utc).isoformat()

    def create_request(self, actor: User, title: str, description: str) -> Dict[str, Any]:
        """Create a new request in Draft status.

        Only Users with Role.CREATOR may create requests.
        Title must be non-empty and <= 120 characters.
        Description must be <= 5000 characters.

        Args:
            actor: User initiating the creation.
            title: Short title summarizing the request.
            description: Detailed body of the request.

        Returns:
            Dict with ok=True and request dict, or ok=False and error details.
        """
        if actor.role != Role.CREATOR:
            return {
                "ok": False,
                "error": {
                    "code": ErrorCode.ROLE_NOT_ALLOWED.value,
                    "message": f"Role '{actor.role.value}' is not allowed to create requests. Only Creators can create.",
                },
            }

        clean_title = (title or "").strip()
        if not clean_title:
            return {
                "ok": False,
                "error": {
                    "code": ErrorCode.VALIDATION_ERROR.value,
                    "message": "Title cannot be empty.",
                },
            }
        if len(clean_title) > MAX_TITLE_LENGTH:
            return {
                "ok": False,
                "error": {
                    "code": ErrorCode.VALIDATION_ERROR.value,
                    "message": f"Title exceeds maximum length of {MAX_TITLE_LENGTH} characters (received {len(clean_title)}).",
                },
            }

        clean_desc = description if description is not None else ""
        if len(clean_desc) > MAX_DESCRIPTION_LENGTH:
            return {
                "ok": False,
                "error": {
                    "code": ErrorCode.VALIDATION_ERROR.value,
                    "message": f"Description exceeds maximum length of {MAX_DESCRIPTION_LENGTH} characters (received {len(clean_desc)}).",
                },
            }

        req_id = f"req_{uuid.uuid4().hex[:8]}"
        now = self._now_iso()

        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                """
                INSERT INTO requests (id, title, description, status, creator_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (req_id, clean_title, clean_desc, Status.DRAFT.value, actor.id, now, now),
            )
            cursor.execute(
                """
                INSERT INTO request_history (request_id, action, from_status, to_status, actor_id, actor_role, reason, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (req_id, "create", "", Status.DRAFT.value, actor.id, actor.role.value, "Draft created", now),
            )
            self._conn.commit()

        return self.get_request(actor, req_id)

    def get_request(self, actor: User, request_id: str) -> Dict[str, Any]:
        """Retrieve a request by its identifier.

        Enforces visibility: Reviewers cannot see Draft requests.

        Args:
            actor: User requesting the record.
            request_id: Identifier of the request.

        Returns:
            Dict with ok=True and request data, or ok=False and error details.
        """
        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                "SELECT id, title, description, status, creator_id, created_at, updated_at FROM requests WHERE id = ?",
                (request_id,),
            )
            row = cursor.fetchone()

        if row is None:
            return {
                "ok": False,
                "error": {
                    "code": ErrorCode.NOT_FOUND.value,
                    "message": f"Request '{request_id}' not found.",
                },
            }

        req_dict = dict(row)

        # Business rule: Reviewers cannot see Drafts
        if req_dict["status"] == Status.DRAFT.value and actor.role == Role.REVIEWER:
            return {
                "ok": False,
                "error": {
                    "code": ErrorCode.NOT_VISIBLE.value,
                    "message": f"Request '{request_id}' is a Draft and not visible to Reviewers.",
                },
            }

        return {"ok": True, "request": req_dict}

    def submit_request(self, actor: User, request_id: str, reason: str = "") -> Dict[str, Any]:
        """Convenience method to transition a Draft to Submitted.

        Delegates to transition_request.
        """
        return self.transition_request(
            actor=actor,
            request_id=request_id,
            action="submit",
            reason=reason or "Submitted for review",
        )

    def transition_request(
        self,
        actor: User,
        request_id: str,
        action: str,
        reason: str = "",
    ) -> Dict[str, Any]:
        """Centralized validation and state transition engine.

        The validation order is strictly enforced:
        1. Unknown action -> UNKNOWN_ACTION
        2. Not found -> NOT_FOUND
        3. Role check -> ROLE_NOT_ALLOWED
        4. Ownership check -> NOT_OWNER
        5. Valid from-status -> INVALID_TRANSITION

        Then executes an atomic UPDATE ... WHERE status = expected to prevent race conditions.

        Args:
            actor: User attempting the state transition.
            request_id: ID of the request to transition.
            action: Action verb ('submit', 'approve', 'reject', 'cancel').
            reason: Optional justification or context for the transition.

        Returns:
            Dict with ok=True and updated request, or ok=False and error details.
        """
        # Step 1: Check for unknown action
        if action not in RULES:
            return {
                "ok": False,
                "error": {
                    "code": ErrorCode.UNKNOWN_ACTION.value,
                    "message": f"Unknown action '{action}'. Valid actions are: {list(RULES.keys())}.",
                },
            }

        rule = RULES[action]

        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                "SELECT id, title, description, status, creator_id, created_at, updated_at FROM requests WHERE id = ?",
                (request_id,),
            )
            row = cursor.fetchone()

            # Step 2: Check for not found
            if row is None:
                return {
                    "ok": False,
                    "error": {
                        "code": ErrorCode.NOT_FOUND.value,
                        "message": f"Request '{request_id}' not found.",
                    },
                }

            current_request = dict(row)
            current_status = current_request["status"]

            # Step 3: Check actor role
            if actor.role != rule.allowed_role:
                return {
                    "ok": False,
                    "error": {
                        "code": ErrorCode.ROLE_NOT_ALLOWED.value,
                        "message": (
                            f"Action '{action}' requires role '{rule.allowed_role.value}', "
                            f"but actor has role '{actor.role.value}'."
                        ),
                    },
                }

            # Step 4: Check ownership
            if rule.owner_only and actor.id != current_request["creator_id"]:
                return {
                    "ok": False,
                    "error": {
                        "code": ErrorCode.NOT_OWNER.value,
                        "message": (
                            f"Action '{action}' can only be performed by the request creator "
                            f"('{current_request['creator_id']}'), but actor is '{actor.id}'."
                        ),
                    },
                }

            # Step 5: Check valid from-status
            allowed_from_values = [s.value for s in rule.from_statuses]
            if current_status not in allowed_from_values:
                return {
                    "ok": False,
                    "error": {
                        "code": ErrorCode.INVALID_TRANSITION.value,
                        "message": (
                            f"Cannot perform '{action}' on request with status '{current_status}'. "
                            f"Allowed source statuses are: {allowed_from_values}."
                        ),
                    },
                }

            # Atomic conditional update to guard against concurrent transitions
            now = self._now_iso()
            target_status = rule.to_status.value

            cursor.execute(
                """
                UPDATE requests
                SET status = ?, updated_at = ?
                WHERE id = ? AND status = ?
                """,
                (target_status, now, request_id, current_status),
            )

            if cursor.rowcount == 0:
                # Another transaction modified this row concurrently
                return {
                    "ok": False,
                    "error": {
                        "code": ErrorCode.CONFLICT.value,
                        "message": "Concurrent state change detected. The request was modified by another operation.",
                    },
                }

            # Record audit history
            cursor.execute(
                """
                INSERT INTO request_history (
                    request_id, action, from_status, to_status, actor_id, actor_role, reason, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request_id,
                    action,
                    current_status,
                    target_status,
                    actor.id,
                    actor.role.value,
                    reason or f"Action '{action}' applied",
                    now,
                ),
            )
            self._conn.commit()

            cursor.execute(
                "SELECT id, title, description, status, creator_id, created_at, updated_at FROM requests WHERE id = ?",
                (request_id,),
            )
            updated_row = dict(cursor.fetchone())

        return {"ok": True, "request": updated_row}

    def get_history(self, actor: User, request_id: str) -> Dict[str, Any]:
        """Retrieve complete transition history for a request.

        Enforces visibility rules first (Reviewers cannot see Draft history).

        Args:
            actor: User requesting the history.
            request_id: Request identifier.

        Returns:
            Dict with ok=True and list of history records, or ok=False and error details.
        """
        access_check = self.get_request(actor, request_id)
        if not access_check["ok"]:
            return access_check

        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(
                """
                SELECT id, request_id, action, from_status, to_status, actor_id, actor_role, reason, timestamp
                FROM request_history
                WHERE request_id = ?
                ORDER BY id ASC
                """,
                (request_id,),
            )
            history = [dict(row) for row in cursor.fetchall()]

        return {"ok": True, "history": history}

    def list_requests(
        self,
        actor: User,
        status: Optional[str] = None,
        creator_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """List requests visible to the actor, with optional filters.

        Reviewers can never see Draft requests.

        Args:
            actor: Current user requesting the list.
            status: Optional status filter.
            creator_id: Optional creator_id filter.

        Returns:
            Dict with ok=True and list of request records.
        """
        # If Reviewer explicitly asks for Drafts, return empty list
        if actor.role == Role.REVIEWER and status == Status.DRAFT.value:
            return {"ok": True, "requests": []}

        conditions = []
        params = []

        if actor.role == Role.REVIEWER:
            conditions.append("status != ?")
            params.append(Status.DRAFT.value)

        if status:
            conditions.append("status = ?")
            params.append(status)

        if creator_id:
            conditions.append("creator_id = ?")
            params.append(creator_id)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        query = f"""
            SELECT id, title, description, status, creator_id, created_at, updated_at
            FROM requests
            {where_clause}
            ORDER BY created_at DESC
        """

        with self._lock:
            cursor = self._conn.cursor()
            cursor.execute(query, tuple(params))
            requests = [dict(row) for row in cursor.fetchall()]

        return {"ok": True, "requests": requests}
