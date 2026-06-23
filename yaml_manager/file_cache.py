"""Small mtime-based cache for repeated UTF-8 text file scans."""

from __future__ import annotations

import threading
from pathlib import Path


class TextFileCache:
    """Cache text files by absolute path, modification time, and size."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._entries: dict[Path, tuple[tuple[int, int], str]] = {}

    def read_text(self, path: Path, max_size: int | None = None) -> str:
        resolved = path.resolve()
        stat = resolved.stat()
        if max_size is not None and stat.st_size > max_size:
            raise OSError(f"{resolved} exceeds the configured maximum file size")
        fingerprint = (stat.st_mtime_ns, stat.st_size)
        with self._lock:
            cached = self._entries.get(resolved)
            if cached and cached[0] == fingerprint:
                return cached[1]

        text = resolved.read_text(encoding="utf-8")
        refreshed = resolved.stat()
        refreshed_fingerprint = (refreshed.st_mtime_ns, refreshed.st_size)
        with self._lock:
            self._entries[resolved] = (refreshed_fingerprint, text)
        return text

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
