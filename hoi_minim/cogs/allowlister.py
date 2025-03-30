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

    def is_allowlisted_id(self, id: int):
        return id in self.allowlisted_users or id in self.allowlisted_roles

    def is_allowlisted_user(self, user: discord.User | discord.Member):
        if isinstance(user, discord.Member):
            return (
                user.guild_permissions.administrator
                or self.is_allowlisted_id(user.id)
                or any(self.is_allowlisted_id(role.id) for role in user.roles)
            )

        return self.is_allowlisted_id(user.id)

    def is_allowlisted_context(self, ctx: commands.Context["MinimBot"]):
        return ctx.author.id == self.bot.owner_id or self.is_allowlisted_user(
            ctx.author
        )

    def get_allowlisted_mentions(self):
        result = ""

        for id in self.allowlisted_users:
            result += f"<@{id}> "

        for id in self.allowlisted_roles:
            result += f"<@&{id}> "

        return result.strip()

    @commands.group("allowlist", invoke_without_command=True)
    async def allowlist(self, ctx: Context):
        pass

    @commands.check_any(
        commands.has_guild_permissions(administrator=True),
        commands.is_owner(),
    )
    @allowlist.command("add")
    async def allowlist_add(
        self, ctx: Context, user_or_role: discord.User | discord.Role
    ):
        if isinstance(user_or_role, discord.User):
            await self.db.execute(
                "INSERT INTO society_whitelist (user_id, role_id) VALUES (?, NULL)",
                (user_or_role.id,),
            )
            await ctx.reply(
                content=f"Added user {user_or_role} to the allowlist.",
                mention_author=False,
            )
        else:
            await self.db.execute(
                "INSERT INTO society_whitelist (user_id, role_id) VALUES (NULL, ?)",
                (user_or_role.id,),
            )
            await ctx.reply(
                content=f"Added role {user_or_role} to the allowlist.",
                mention_author=False,
            )

        await self._reload_allowlist()

    @commands.check_any(
        commands.has_guild_permissions(administrator=True),
        commands.is_owner(),
    )
    @allowlist.command("remove")
    async def allowlist_remove(
        self, ctx: Context, user_or_role: discord.User | discord.Role
    ):
        await self.db.execute(
            "DELETE FROM society_whitelist WHERE user_id = ? or role_id = ?",
            (user_or_role.id, user_or_role.id),
        )
        await ctx.reply(
            f"Removed {user_or_role} from the allowlist.",
            mention_author=False,
        )
        await self._reload_allowlist()


async def setup(bot: "MinimBot"):
    await bot.add_cog(AllowlisterCog(bot))
