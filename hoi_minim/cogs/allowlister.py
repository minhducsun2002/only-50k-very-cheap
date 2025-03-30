from typing import TYPE_CHECKING, override

import discord
from discord.ext import commands
from discord.ext.commands import Context

if TYPE_CHECKING:
    from hoi_minim.bot import MinimBot
    from hoi_minim.cogs.database import DatabaseCog


class AllowlisterCog(commands.Cog, name="Allowlister"):
    def __init__(self, bot: "MinimBot") -> None:
        self.bot: "MinimBot" = bot
        self.db: "DatabaseCog" = self.bot.get_cog("Database")  # pyright: ignore[reportAttributeAccessIssue]

        self.allowlisted_users: list[int] = []
        self.allowlisted_roles: list[int] = []

    @override
    async def cog_load(self) -> None:
        self.db = self.bot.get_cog("Database")  # pyright: ignore[reportAttributeAccessIssue]
        await self._reload_allowlist()

    @override
    def cog_check(self, ctx: Context["MinimBot"]) -> bool:
        return self.is_allowlisted_context(ctx)

    async def _reload_allowlist(self):
        query = "SELECT role_id, user_id FROM society_whitelist"
        result = await self.db.execute(query)

        self.allowlisted_users.clear()
        self.allowlisted_roles.clear()

        for row in result:
            if row[0] is not None:
                self.allowlisted_roles.append(row[0])
            elif row[1] is not None:
                self.allowlisted_users.append(row[1])

    def is_allowlisted(self, id: int):
        return id in self.allowlisted_users or id in self.allowlisted_roles

    def is_allowlisted_context(self, ctx: commands.Context["MinimBot"]):
        return (
            ctx.author.id == self.bot.owner_id
            or (
                isinstance(ctx.author, discord.Member)
                and (
                    ctx.author.guild_permissions.administrator
                    or any(
                        role.id in self.allowlisted_roles for role in ctx.author.roles
                    )
                )
            )
            or ctx.author.id in self.allowlisted_users
        )

    def get_allowlisted_mentions(self):
        result = ""

        for id in self.allowlisted_users:
            result += f"<@{id}> "

        for id in self.allowlisted_roles:
            result += f"<@&{id}> "

        return result.strip()


async def setup(bot: "MinimBot"):
    await bot.add_cog(AllowlisterCog(bot))
