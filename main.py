import asyncio
import importlib.util
import sys
from typing import Callable

from hoi_minim.bot import MinimBot


def get_event_loop_factory() -> Callable[[], asyncio.AbstractEventLoop] | None:
    if sys.platform == "win32" and importlib.util.find_spec("winloop"):
        import winloop  # pyright: ignore[reportMissingImports]

        return winloop.new_event_loop  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]

    if sys.platform != "win32" and importlib.util.find_spec("uvloop"):
        import uvloop  # pyright: ignore[reportMissingImports]

        return uvloop.new_event_loop  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]

    return None


async def main():
    bot = MinimBot()

    async with bot:
        await bot.start()


if __name__ == "__main__":
    with asyncio.Runner(loop_factory=get_event_loop_factory()) as runner:
        runner.run(main())
