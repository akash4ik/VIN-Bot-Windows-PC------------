from __future__ import annotations

import os
from pathlib import Path
from types import TracebackType
from typing import Self


class SingleInstanceError(RuntimeError):
    pass


class SingleInstanceLock:
    """Keep one bot process per data directory.

    Windows releases the byte-range lock automatically if the process exits or
    is terminated, so a stale lock file does not prevent the next start.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._file = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("a+b")
        self._file.seek(0)
        if self._file.read(1) == b"":
            self._file.seek(0)
            self._file.write(b"0")
            self._file.flush()
        self._file.seek(0)

        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self._file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self._file.close()
            self._file = None
            raise SingleInstanceError(
                "VIN-бот уже запущен. Сначала остановите существующий процесс."
            ) from exc

        self._file.seek(0)
        self._file.truncate()
        self._file.write(str(os.getpid()).encode("ascii"))
        self._file.flush()

    def release(self) -> None:
        if self._file is None:
            return
        try:
            self._file.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
        finally:
            self._file.close()
            self._file = None

    def __enter__(self) -> Self:
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.release()
