from pathlib import Path

import apsw
from apsw import SQLITE_OPEN_CREATE, SQLITE_OPEN_READWRITE

from .connection import Connection
from .cursor import Cursor
from .types import APSWExecuteKwargs

__all__ = ("APSWExecuteKwargs", "Connection", "Cursor")


def connect(
    filename: str | Path,
    flags: int = SQLITE_OPEN_READWRITE | SQLITE_OPEN_CREATE,
    vfs: str | None = None,
    statementcachesize: int = 100,
):
    def connector():
        return apsw.Connection(str(filename), flags, vfs, statementcachesize)

    return Connection(connector)
