"""Structured errors, written so an LLM agent can read them and act sensibly."""

from __future__ import annotations

from typing import Any

# CLI exit codes (design doc §4). Anything not listed exits 1.
EXIT_OK = 0
EXIT_QUEUED = 75
EXIT_PAUSED = 76
EXIT_REVOKED = 77

DEFAULT_HINTS = {
    "LEASE_PAUSED": (
        "A human has paused your board. Do not retry hardware tools. Work on code, "
        "or call wait_for_board(ticket) to resume; your place is kept."
    ),
    "LEASE_REVOKED": (
        "Your lease was ended. Stop hardware work. If a ticket is included you were "
        "re-queued; call wait_for_board(ticket) to get the board back."
    ),
    "LEASE_EXPIRED": (
        "Your lease ran out (no hardware activity before the TTL). Call acquire_board "
        "again when you are ready to use the board."
    ),
    "LEASE_UNKNOWN": "That lease token is not known. Call acquire_board to get a board.",
    "TICKET_UNKNOWN": "That ticket is not known. Call acquire_board again.",
    "TICKET_EXPIRED": (
        "Your queue ticket expired because it was not polled. Call acquire_board again."
    ),
    "BOARD_BUSY": "Another operation is running on this lease. Wait for it to finish.",
    "BOARD_OFFLINE": "The board's probe is not connected. Tell the human; do not retry in a loop.",
    "NEEDS_APPROVAL": (
        "This action needs the human's approval in the dashboard. Call the same tool "
        "again later with the same arguments to see the result."
    ),
    "APPROVAL_DENIED": "The human declined this action. Do not ask again for this lease.",
    "NOT_SUPPORTED": "This board or its driver does not support that action.",
    "OUT_OF_RANGE": "The value is outside what this board allows.",
    "OP_FAILED": "The operation failed. Read the log tail; fix the cause before retrying.",
    "TIMEOUT": "The operation timed out.",
    "UNAUTHORIZED": "Missing or wrong arbiter token.",
    "BAD_REQUEST": "The request was malformed.",
    "BOARD_UNKNOWN": "No board matches. Call list_boards to see what exists.",
    "SESSION_UNKNOWN": "Unknown session. Register again.",
}

HTTP_STATUS = {
    "UNAUTHORIZED": 401,
    "BAD_REQUEST": 400,
    "BOARD_UNKNOWN": 404,
    "LEASE_UNKNOWN": 404,
    "TICKET_UNKNOWN": 404,
    "SESSION_UNKNOWN": 404,
}

EXIT_CODES = {
    "LEASE_PAUSED": EXIT_PAUSED,
    "LEASE_REVOKED": EXIT_REVOKED,
    "LEASE_EXPIRED": EXIT_REVOKED,
}


class ArbiterError(Exception):
    def __init__(self, code: str, message: str = "", hint: str | None = None, **extra: Any):
        super().__init__(message or code)
        self.code = code
        self.message = message or code.replace("_", " ").lower()
        self.hint = hint if hint is not None else DEFAULT_HINTS.get(code, "")
        self.extra = extra

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"error": self.code, "message": self.message}
        d.update({k: v for k, v in self.extra.items() if v is not None})
        if self.hint:
            d["hint"] = self.hint
        return d

    @property
    def http_status(self) -> int:
        return HTTP_STATUS.get(self.code, 409)

    @property
    def exit_code(self) -> int:
        return EXIT_CODES.get(self.code, 1)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ArbiterError:
        extra = {k: v for k, v in d.items() if k not in ("error", "message", "hint")}
        return cls(d.get("error", "OP_FAILED"), d.get("message", ""), d.get("hint"), **extra)
