import traceback
from typing import TYPE_CHECKING, NotRequired, TypedDict, Unpack

import apsw.ext
import apsw.fts5
import discord
from discord.ext import commands
from discord.ext.commands import Cog, Context

if TYPE_CHECKING:
    from apsw import Bindings

    from hoi_minim.bot import MinimBot


class APSWExecuteKwargs(TypedDict):
    can_cache: NotRequired[bool]
    prepare_flags: NotRequired[int]
    explain: NotRequired[int]


class DatabaseCog(Cog, name="Database"):
    def __init__(self, bot: "MinimBot") -> None:
        self.bot: "MinimBot" = bot
        self.tag_lookup_search: apsw.fts5.Table = apsw.fts5.Table(
            self.bot.connection, "tag_lookup_search"
        )

    @property
    def connection(self):
        return self.bot.connection

    async def _execute(
        self,
        connection: apsw.Connection,
        statements: str,
        bindings: "Bindings | None" = None,
        **kwargs: Unpack[APSWExecuteKwargs],
    ):
        return await self.bot.loop.run_in_executor(
            None,
            lambda: connection.execute(statements, bindings, **kwargs),
        )

    async def execute(
        self,
        statements: str,
        bindings: "Bindings | None" = None,
        **kwargs: Unpack[APSWExecuteKwargs],
    ):
        return await self._execute(self.connection, statements, bindings, **kwargs)

    @commands.is_owner()
    @commands.command("sqlexec")
    async def sqlexec(self, ctx: Context, *, query: str):
        try:
            result = await self.bot.loop.run_in_executor(
                None,
                lambda: apsw.ext.format_query_table(self.connection, query),
            )
        except apsw.Error as e:
            await ctx.reply(
                embed=discord.Embed(
                    color=discord.Color.red(),
                    title="Error",
                    description=(
                        f"Could not execute SQL query:\n```\n{'\n'.join(traceback.format_exception(e))}\n```"
                    ),
                ),
                mention_author=False,
            )
            return

        content = f"```sql\n{query}\n```\n```\n{result}\n```"

        if len(content) > 2000:
            await ctx.reply(
                embed=discord.Embed(
                    color=discord.Color.red(),
                    title="Error",
                    description="Query result is too large. Maybe try limiting your query?",
                ),
                mention_author=False,
            )
            return

        await ctx.reply(
            content=(f"```sql\n{query}\n```\n```\n{result}\n```"),
            mention_author=False,
        )


async def setup(bot: "MinimBot"):
    await bot.add_cog(DatabaseCog(bot))
