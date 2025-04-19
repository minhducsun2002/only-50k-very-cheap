import random
from datetime import timedelta
from typing import TYPE_CHECKING, cast, override

import discord
import structlog
from discord.ext import commands
from discord.ext.commands import Context

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
    "n1gger",
    "n1993r",
    "にggあ",
    "닉가",
    "Ɲ𝐼𝓘𝓘𝑒ℛ",
    "nagger",
    "ligger",
    "ligga",
    "gigger",
    "negus",
    "igga",
    "igger",
    "nigget",
    "nugger",
    "nickgur",
    "gga",
    "gger",
}


class NwordMuter(commands.Cog):
    def __init__(self, bot: "MinimBot") -> None:
        self.bot = bot
        self.allowlister: "AllowlisterCog" = self.bot.get_cog("Allowlister")  # pyright: ignore[reportAttributeAccessIssue]

        self.random = random.Random()
        self.random.seed()

        self.mute_pity: int = 7

    @override
    async def cog_load(self) -> None:
        cursor = await self.bot.db.execute(
            "SELECT value FROM bot_config WHERE key = 'racism-max-pity'"
        )
        pity = await cursor.get()

        if pity is not None:
            self.mute_pity = int(pity)

    @commands.command("max_pity")
    @commands.is_owner()
    async def set_max_pity(self, ctx: Context, max_pity: int | None = None):
        if max_pity is None:
            cursor = await self.bot.db.execute(
                "SELECT value FROM bot_config WHERE key = 'racism-max-pity'"
            )
            pity = await cursor.get()
            pity = int(pity) if pity is not None else 7

            await ctx.reply(
                content=f"Current mute pity is {pity}.", mention_author=False
            )
            return

        self.mute_pity = max_pity

        await self.bot.db.execute(
            "INSERT INTO bot_config(key, value) VALUES ('racism-max-pity', ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            (max_pity,),
        )

        await ctx.reply(
            f"Set max pity to {max_pity} times.",
            mention_author=False,
            allowed_mentions=discord.AllowedMentions.none(),
        )

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
        has_racism_in_display_name = any(
            word in ("nigga", "nigger", "niggas", "niggers") or forbidden_word in word
            for forbidden_word in WORDLIST
            for word in author.display_name.lower().split()
        )
        has_racism = has_racism_in_display_name or any(
            word not in ("nigga", "nigger", "niggas", "niggers")
            and forbidden_word in word
            for forbidden_word in WORDLIST
            for word in message.content.lower().split()
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
        max_pity = self.mute_pity
        pity: int = (await pity_cursor.get()) or 0
        rand_number = self.random.random()
        logger.debug("current pity", user_id=author.id, pity=pity)
        getting_hard_muted = rand_number < 0.001
        getting_muted = rand_number < 0.12 or pity >= max_pity
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

        if getting_hard_muted:
            logger.debug("user hit URacism", user_id=author.id)
        else:
            logger.debug("user hit SSRacism", user_id=author.id)

        try:
            await message.delete()
            if getting_hard_muted:
                await author.timeout(timedelta(days=7), reason="sorako")
            else:
                await author.timeout(timedelta(hours=1), reason="sorako")
        except (discord.errors.Forbidden, discord.errors.HTTPException) as e:
            logger.exception("could not time out racism", exc_info=e)

        try:
            reason_vi = "bypass n-word filter"
            reason_en = "bypassing the n-word filter"

            if has_racism_in_display_name:
                reason_vi = "đặt nickname có n-word"
                reason_en = "having the n-word in your display name"

            dm_channel = author.dm_channel or await author.create_dm()
            if getting_hard_muted:
                await dm_channel.send(
                    content=(
                        f"Bạn đã bị mute do {reason_vi}. Bạn rất tốt nhưng tôi rất tiếc, vì đầu cu hậu quả hiếm khi được bôi trơn.\n"
                        f"You have been muted for {reason_en}. Unfortunately for you the dildo of consequences rarely comes lubed."
                    )
                )
            elif pity >= max_pity:
                await dm_channel.send(
                    content=(
                        f"Bạn đã bị mute do {reason_vi} và do đạt ngưỡng pity. Bạn có tối đa {max_pity} lượt bypass filter trước khi bị mute.\n"
                        f"You have been muted for {reason_en}, and reaching pity. You can bypass the filter {max_pity} times at max before getting muted."
                    )
                )
            else:
                await dm_channel.send(
                    content=(
                        f"Bạn đã bị mute do {reason_vi} và do xui. Bạn có 12% khả năng bị mute mỗi lần bypass filter.\n"
                        f"You have been muted for {reason_en}, and for being unlucky. There's only a 12% chance you get muted for doing so."
                    )
                )
        except (discord.errors.Forbidden, discord.errors.HTTPException) as e:
            logger.exception("cannot notify mute", exc_info=e)


async def setup(bot: "MinimBot"):
    await bot.add_cog(NwordMuter(bot))
