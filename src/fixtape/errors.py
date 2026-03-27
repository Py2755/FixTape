from __future__ import annotations


class FixTapeError(RuntimeError):
    """Base FixTape error."""


class NoActiveSessionError(FixTapeError):
    """Raised when no active session exists."""


class ActiveSessionExistsError(FixTapeError):
    """Raised when another session is already active."""
