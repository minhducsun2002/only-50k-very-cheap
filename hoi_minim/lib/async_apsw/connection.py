from collections.abc import Callable, Generator, Iterable
from functools import partial
from types import TracebackType
from typing import TYPE_CHECKING, Any, Self, Unpack

import anyio.to_thread
import apsw

from ._sentinel import Sentinel
from .cursor import Cursor
from .types import APSWExecuteKwargs

if TYPE_CHECKING:
    from apsw import Bindings

_MISSING: Any = Sentinel()
_STOP_RUNNING: Any = Sentinel()


class Connection:
    def __init__(
        self,
        connector: Callable[[], apsw.Connection],
    ) -> None:
        super().__init__()
        self._running = True
        self._connection: apsw.Connection = _MISSING
        self._connector = connector

    @property
    def connection(self):
        return self._connection

    async def _connect(self) -> Self:
        if self._connection is _MISSING:
            try:
                self._connection = await anyio.to_thread.run_sync(self._connector)
            except apsw.Error:
                self._running = False
                self._connection = _MISSING
                raise

        return self

    def __await__(self) -> Generator[Any, None, Self]:
        return self._connect().__await__()

    async def __aenter__(self) -> Self:
        await anyio.to_thread.run_sync(self._connection.__enter__)
        return await self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ):
        await anyio.to_thread.run_sync(
            self._connection.__exit__, exc_type, exc_val, exc_tb
        )

    async def execute(
        self,
        statements: str,
        bindings: "Bindings | None" = None,
        **kwargs: Unpack[APSWExecuteKwargs],
    ):
        fn = partial(self._connection.execute, statements, bindings, **kwargs)
        cursor = await anyio.to_thread.run_sync(fn)

        return Cursor(self._connection, cursor)

    async def executemany(
        self,
        statements: str,
        sequenceofbindings: Iterable["Bindings"],
        **kwargs: Unpack[APSWExecuteKwargs],
    ):
        fn = partial(
            self._connection.executemany, statements, sequenceofbindings, **kwargs
        )
        cursor = await anyio.to_thread.run_sync(fn)

        return Cursor(self._connection, cursor)

    async def close(self, *, force: bool = False):
        return await anyio.to_thread.run_sync(self._connection.close, force)
