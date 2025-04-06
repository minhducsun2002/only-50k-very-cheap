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
    "nіgga",  # noqa: RUF001
    "nіggеr",  # noqa: RUF001
    "ngga",
    "ngger",
    "n199er",
    "n199a",
    "n/gget",
    "Ꞃい𝔾𝔾えR",  # noqa: RUF001
    "nıgus",  # noqa: RUF001
    "Ꞃ𝕚𝔾𝔾Ꭼr",  # noqa: RUF001
    "ɴɪɢɢᴇʀ",
    "nigg3r",
    "n1gg3r",
    "n1993r",
    "にggあ",
    "닉가",
    "Ɲ𝐼𝓘𝓘𝑒ℛ",
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
            forbidden_word.lower() in word.lower()
            for forbidden_word in WORDLIST
            for word in message.content.split()
        )

        if not has_racism:
            return

        logger.debug(
            "detected racism",
            channel_id=message.channel.id,
            message_id=message.id,
            user_id=author.id,
        )
        getting_muted = self.random.random() < 0.12
        can_be_muted = author.top_role < message.guild.me.top_role

        if not getting_muted:
            return

        if not can_be_muted:
            logger.debug(
                "user hit SSRacism, but cannot be muted",
                user_id=author.id,
                user_top_role=author.top_role.id,
            )
            return

        logger.debug("user hit SSRacism", user_id=author.id)

        try:
            await author.timeout(timedelta(hours=1), reason="sorako")
        except (discord.errors.Forbidden, discord.errors.HTTPException) as e:
            logger.exception("could not time out racism", exc_info=e)

        try:
            dm_channel = author.dm_channel or await author.create_dm()

            await dm_channel.send(
                content=(
                    "Bạn đã bị mute do n-word bypass và do xui. Bạn có 12% khả năng bị mute mỗi lần bypass filter.\n"
                    "You have been muted for bypassing the n-word filter, and for being unlucky. There's only a 12% chance you get muted for doing so."
                )
            )
        except (discord.errors.Forbidden, discord.errors.HTTPException) as e:
            logger.exception("cannot notify mute", exc_info=e)


async def setup(bot: "MinimBot"):
    await bot.add_cog(NwordMuter(bot))
