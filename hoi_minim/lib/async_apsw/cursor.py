from collections.abc import Iterable
from functools import partial
from typing import TYPE_CHECKING, Unpack

import anyio.to_thread
import apsw

from .types import APSWExecuteKwargs

if TYPE_CHECKING:
    from apsw import Bindings


class Cursor:
    def __init__(self, connection: apsw.Connection, cursor: apsw.Cursor) -> None:
        self.connection = connection
        self._cursor = cursor

    async def close(self, *, force: bool = False):
        return await anyio.to_thread.run_sync(self._cursor.close, force)

    async def get(self):
        return await anyio.to_thread.run_sync(lambda: self._cursor.get)

    async def execute(
        self,
        statements: str,
        bindings: "Bindings | None" = None,
        **kwargs: Unpack[APSWExecuteKwargs],
    ):
        fn = partial(self._cursor.execute, statements, bindings, **kwargs)
        cursor = await anyio.to_thread.run_sync(fn)

        return Cursor(self.connection, cursor)

    async def executemany(
        self,
        statements: str,
        sequenceofbindings: Iterable["Bindings"],
        **kwargs: Unpack[APSWExecuteKwargs],
    ):
        fn = partial(self._cursor.executemany, statements, sequenceofbindings, **kwargs)
        cursor = await anyio.to_thread.run_sync(fn)

        return Cursor(self.connection, cursor)

    async def fetchall(self):
        return await anyio.to_thread.run_sync(self._cursor.fetchall)

    async def fetchone(self):
        return await anyio.to_thread.run_sync(self._cursor.fetchone)
