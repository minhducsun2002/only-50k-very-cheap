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
    "nger",
    "nagger",
    "nige",
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
            forbidden_word in word.lower()
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
        pity_cursor = await self.bot.db.execute(
            "SELECT count FROM racism_pity_counter WHERE guild_id = ? AND user_id = ?",
            (message.guild.id, author.id),
        )
        pity: int = (await pity_cursor.get()) or 0

        logger.debug("current pity", user_id=author.id, pity=pity)
        getting_muted = self.random.random() < 0.12 or pity >= 7
        can_be_muted = author.top_role < message.guild.me.top_role

        if not can_be_muted:
            return

        if not getting_muted:
            if can_be_muted:
                await self.bot.db.execute(
                    """INSERT INTO racism_pity_counter (guild_id, user_id, count)
                    VALUES (?, ?, 1)
                    ON CONFLICT (guild_id, user_id) DO UPDATE SET count = count + 1""",
                    (message.guild.id, author.id),
                )
            return

        await self.bot.db.execute(
            "UPDATE racism_pity_counter SET count = 0 WHERE guild_id = ? and user_id = ?",
            (message.guild.id, author.id),
        )

        logger.debug("user hit SSRacism", user_id=author.id)

        try:
            await message.delete()
            await author.timeout(timedelta(hours=1), reason="sorako")
        except (discord.errors.Forbidden, discord.errors.HTTPException) as e:
            logger.exception("could not time out racism", exc_info=e)

        try:
            dm_channel = author.dm_channel or await author.create_dm()

            if pity >= 7:
                await dm_channel.send(
                    content=(
                        "Bạn đã bị mute do n-word bypass và do đạt ngưỡng pity. Bạn có tối đa 7 lượt bypass filter trước khi bị mute.\n"
                        "You have been muted for bypassing the n-word filter, and reaching pity. You can bypass the filter 7 times at max before getting muted."
                    )
                )
            else:
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
