"""Shared application exceptions."""

from __future__ import annotations

from typing import Any


class ApiError(Exception):
    """An expected error that can be returned by the HTTP API."""

    def __init__(self, status: int, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.details = details or {}
