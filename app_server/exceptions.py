"""Shared app-server exceptions."""

from __future__ import annotations


class AppServerError(Exception):
    """Base orchestration-layer error."""


class NotFoundError(AppServerError):
    """Raised when a requested resource does not exist."""


class ConflictError(AppServerError):
    """Raised when the current state does not allow the requested action."""


class UpstreamError(AppServerError):
    """Raised when Redis or DB dependencies fail unexpectedly."""

