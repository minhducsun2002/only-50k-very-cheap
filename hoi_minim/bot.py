import asyncio
import contextlib
import signal
from typing import override

import apsw
import apsw.bestpractice
import apsw.fts5
import discord
import structlog
from discord.ext import commands
from discord.ext.commands import Bot, ExtensionError
from discord.utils import MISSING  # pyright: ignore[reportAny]

from .lib import async_apsw
from .migrator import Migrator
from .settings import settings

logger: structlog.stdlib.BoundLogger = structlog.get_logger()
EXTENSIONS = (
    "hoi_minim.cogs.allowlister",
    "hoi_minim.cogs.demons",
    "hoi_minim.cogs.tags",
    "hoi_minim.cogs.nword_muter",
)


class KeyboardInterruptHandler:
    def __init__(self, bot: Bot):
        self.bot: Bot = bot
        self._task: asyncio.Task[None] | None = None

    def __call__(self):
        if self._task:
            raise KeyboardInterrupt
        self._task = asyncio.create_task(self.bot.close())


class MinimBot(Bot):
    @override
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True

        command_prefix = commands.when_mentioned_or("l>")

        super().__init__(command_prefix=command_prefix, intents=intents)

        self.db: async_apsw.Connection = MISSING
        self.bot_app_info: discord.AppInfo = MISSING

    @override
    async def setup_hook(self) -> None:
        handler = KeyboardInterruptHandler(self)

        with contextlib.suppress(NotImplementedError):
            self.loop.add_signal_handler(signal.SIGTERM, handler)
            self.loop.add_signal_handler(signal.SIGINT, handler)

        self.bot_app_info = await self.application_info()
        self.owner_id = self.bot_app_info.owner.id  # pyright: ignore[reportUnannotatedClassAttribute]

        apsw.bestpractice.apply(apsw.bestpractice.recommended)  # pyright: ignore[reportUnknownMemberType]

        settings.database_path.parent.mkdir(parents=True, exist_ok=True)

        self.db = await async_apsw.connect(settings.database_path)

        apsw.fts5.register_functions(  # pyright: ignore[reportUnknownMemberType]
            self.db.connection,
            apsw.fts5.map_functions,  # pyright: ignore[reportArgumentType]
        )
        apsw.fts5.register_tokenizers(  # pyright: ignore[reportUnknownMemberType]
            self.db.connection,
            apsw.fts5.map_tokenizers,  # pyright: ignore[reportArgumentType]
        )

        migrator = Migrator()
        await self.loop.run_in_executor(
            None, lambda: migrator.upgrade(self.db.connection)
        )

        for extension in EXTENSIONS:
            try:
                await self.load_extension(extension)
            except ExtensionError as e:
                await logger.aexception("could not load extension", exc_info=e)

    @override
    async def start(self, *, reconnect: bool = True) -> None:  # pyright: ignore[reportIncompatibleMethodOverride]
        return await super().start(settings.discord_token, reconnect=reconnect)

    @override
    async def close(self) -> None:
        await self.db.close()
        return await super().close()
