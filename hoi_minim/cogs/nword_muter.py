import contextlib
import random
from datetime import timedelta
from typing import TYPE_CHECKING, cast

import discord
import structlog
from discord.ext import commands

if TYPE_CHECKING:
    from hoi_minim.bot import MinimBot
    from hoi_minim.cogs.allowlister import AllowlisterCog

logger: structlog.stdlib.BoundLogger = structlog.get_logger()

WORDLIST = {
    "nlgga",
    "nlgger",
    "n/gga",
    "n/gger",
    "niga",
    "niger",
    "nigga",
    "nigger",
    "nіgga",  # noqa: RUF001
    "nіggеr",  # noqa: RUF001
}


class NwordMuter(commands.Cog):
    def __init__(self, bot: "MinimBot") -> None:
        self.bot = bot
        self.allowlister: "AllowlisterCog" = self.bot.get_cog("Allowlister")  # pyright: ignore[reportAttributeAccessIssue]

        self.random = random.Random()
        self.random.seed()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.channel.id in self.allowlister.thread_ids:
            return

        if message.author.bot:
            return

        if message.webhook_id:
            return

        if message.guild is None:
            return

        author = cast(discord.Member, message.author)
        has_racism = any(
            forbidden_word in word
            for forbidden_word in WORDLIST
            for word in message.content.split()
        )

        if not has_racism:
            return

        getting_muted = self.random.random() < 0.2

        if not getting_muted:
            return

        with contextlib.suppress(
            discord.errors.Forbidden, discord.errors.HTTPException
        ):
            await author.timeout(timedelta(hours=1), reason="sorako")


async def setup(bot: "MinimBot"):
    await bot.add_cog(NwordMuter(bot))
