import io
from typing import TYPE_CHECKING, Annotated, override

import apsw
import discord
from discord.ext import commands
from discord.ext.commands import Context

from hoi_minim.lib.pagination import PageSourceProtocol, PaginationView

if TYPE_CHECKING:
    from hoi_minim.bot import MinimBot
    from hoi_minim.cogs.allowlister import AllowlisterCog
    from hoi_minim.cogs.database import DatabaseCog


class TagPageSource(PageSourceProtocol):
    def __init__(self, db: "DatabaseCog", guild_id: int, *, per_page: int):
        self.db: "DatabaseCog" = db
        self.guild_id: int = guild_id
        self.per_page: int = per_page

    async def get_count(self):
        query = "SELECT COUNT(id) FROM tags WHERE guild_id = ?"
        result = await self.db.execute(query, (self.guild_id,))
        count: int = result.get

        return count

    @override
    async def is_paginating(self) -> bool:
        return await self.get_count() > self.per_page

    @override
    async def get_max_pages(self) -> int | None:
        pages, left_over = divmod(await self.get_count(), self.per_page)

        if left_over:
            pages += 1

        return pages

    @override
    async def get_page(self, page_number: int):
        query = (
            "SELECT id, name FROM tags WHERE guild_id = ? ORDER BY id LIMIT 10 OFFSET ?"
        )
        offset = page_number * self.per_page
        result = await self.db.execute(query, (self.guild_id, offset))

        return result.fetchall()

    @override
    async def format_page(
        self, menu: "PaginationView", page: list[tuple[int, str]]
    ) -> discord.Embed:
        description = ""

        for tag in page:
            description += f"`{tag[0]}` {tag[1]}\n"

        return discord.Embed(
            color=discord.Color.yellow(),
            title="Tag list",
            description=description,
        )


class TagName(commands.clean_content):
    def __init__(self, *, lower: bool = False):
        self.lower = lower
        super().__init__()

    async def convert(self, ctx: Context, argument: str) -> str:
        converted = await super().convert(ctx, argument)
        lower = converted.lower().strip()

        if not lower:
            msg = "Missing tag name."
            raise commands.BadArgument(msg)

        if len(lower) > 100:
            msg = "Tag name is a maximum of 100 characters."
            raise commands.BadArgument(msg)

        first_word, _, _ = lower.partition(" ")

        # get tag command.
        root: commands.GroupMixin = ctx.bot.get_command("tag")

        if first_word in root.all_commands:
            msg = "This tag name starts with a reserved word."
            raise commands.BadArgument(msg)

        return lower if self.lower else converted.strip()


class TagsCog(commands.Cog, name="Tags"):
    def __init__(self, bot: "MinimBot") -> None:
        self.bot: "MinimBot" = bot
        self.db: "DatabaseCog" = self.bot.get_cog("Database")  # pyright: ignore[reportAttributeAccessIssue]
        self.allowlister: "AllowlisterCog" = self.bot.get_cog("Allowlister")  # pyright: ignore[reportAttributeAccessIssue]

    @override
    def cog_check(self, ctx: Context["MinimBot"]) -> bool:
        return self.allowlister.is_allowlisted_context(ctx)

    @commands.guild_only()
    @commands.group(name="tag", invoke_without_command=True)
    async def tag(self, ctx: Context, *, name: Annotated[str, TagName(lower=True)]):
        query = """
        SELECT tags.content
        FROM tag_lookup
        LEFT JOIN tags ON tags.id = tag_lookup.tag_id
        WHERE tag_lookup.guild_id = ? AND LOWER(tag_lookup.name) = ?
        """
        search_query = """
        SELECT tag_lookup_search.name
        FROM tag_lookup_search(?)
        LEFT JOIN tag_lookup ON tag_lookup.id = tag_lookup_search.rowid
        WHERE tag_lookup.guild_id = ?
        ORDER BY rank
        LIMIT 3
        """

        if ctx.guild is None:
            msg = "ctx.guild is None in guild only command"
            raise RuntimeError(msg)

        cursor = await self.db.execute(query, (ctx.guild.id, name))
        row = cursor.fetchone()

        if row is None:
            cursor = await self.db.execute(search_query, (name, ctx.guild.id))
            options = [row[0] for row in cursor]

            content = "Tag not found."

            if len(options) > 0:
                content += f" Did you mean...\n{'\n'.join(options)}"

            await ctx.reply(
                content=content,
                mention_author=False,
            )
            return

        await ctx.reply(content=row[0], mention_author=False)

    @commands.guild_only()
    @tag.command(name="create", aliases=["add"])
    async def tag_create(
        self,
        ctx: Context,
        name: Annotated[str, TagName],
        *,
        content: Annotated[str, commands.clean_content],
    ):
        tag_create_query = """
        INSERT INTO tags (name, content, owner_id, guild_id)
        VALUES (?, ?, ?, ?)
        RETURNING id
        """
        tag_lookup_create_query = """
        INSERT INTO tag_lookup (name, tag_id, owner_id, guild_id)
        VALUES (?, ?, ?, ?);
        """

        if ctx.guild is None:
            msg = "ctx.guild is None in guild only command"
            raise RuntimeError(msg)

        with self.db.connection:
            try:
                cursor = await self.db.execute(
                    tag_create_query, (name, content, ctx.author.id, ctx.guild.id)
                )
            except apsw.ConstraintError:
                await ctx.reply(
                    content="This tag already exists.", mention_author=False
                )
                raise
            except apsw.Error:
                await ctx.reply(content="Could not create tag.", mention_author=False)
                raise

            tag_id_row = cursor.fetchone()

            if tag_id_row is None:
                await ctx.reply(content="Could not create tag.", mention_author=False)

                msg = "Missing tag ID row after creation"
                raise Exception(msg)  # noqa: TRY002

            tag_id = tag_id_row[0]

            try:
                cursor = await self.db.execute(
                    tag_lookup_create_query, (name, tag_id, ctx.author.id, ctx.guild.id)
                )
            except apsw.ConstraintError:
                await ctx.reply(
                    content="This tag already exists.", mention_author=False
                )
                raise
            except apsw.Error:
                await ctx.reply(content="Could not create tag.", mention_author=False)
                raise

        await ctx.reply(
            content=f"Tag {name} successfully created.", mention_author=False
        )

    @commands.guild_only()
    @tag.command(name="alias")
    async def tag_alias(
        self,
        ctx: Context,
        new_name: Annotated[str, TagName],
        old_name: Annotated[str, TagName],
    ):
        query_select = """
        SELECT tag_id, guild_id
        FROM tag_lookup
        WHERE guild_id = ? AND LOWER(name) = ?
        """
        query_insert = """
        INSERT INTO tag_lookup (name, tag_id, owner_id, guild_id)
        VALUES (?, ?, ?, ?)
        """

        if ctx.guild is None:
            msg = "ctx.guild is None in guild only command"
            raise RuntimeError(msg)

        cursor = await self.db.execute(query_select, (ctx.guild.id, old_name.lower()))
        row = cursor.fetchone()

        if row is None:
            await ctx.reply(
                f"A tag with the name of {old_name} does not exist.",
                mention_author=False,
            )
            return

        tag_id, guild_id = row

        with self.db.connection:
            try:
                await self.db.execute(
                    query_insert, (new_name, tag_id, ctx.author.id, guild_id)
                )
                await ctx.reply(
                    f"Tag alias {new_name} that points to {old_name} successfully created.",
                    mention_author=False,
                )
            except apsw.ConstraintError:
                await ctx.reply(
                    content="A tag with this name already exists.", mention_author=False
                )
                raise
            except apsw.Error:
                await ctx.reply(
                    content="Could not create tag alias.", mention_author=False
                )
                raise

    @commands.guild_only()
    @tag.command(name="edit")
    async def tag_edit(
        self,
        ctx: Context,
        name: Annotated[str, TagName(lower=True)],
        *,
        content: Annotated[str, commands.clean_content],
    ):
        query_select = """
        SELECT id
        FROM tags
        WHERE LOWER(name) = ? AND owner_id = ? AND guild_id = ?
        """
        query_update = """
        UPDATE tags SET content = ? WHERE id = ?
        """

        if ctx.guild is None:
            msg = "ctx.guild is None in guild only command"
            raise RuntimeError(msg)

        cursor = await self.db.execute(
            query_select, (name, ctx.author.id, ctx.guild.id)
        )
        row = cursor.fetchone()

        if row is None:
            await ctx.reply(
                content="Could not find a tag with that name, are you sure it exists or you own it?",
                mention_author=False,
            )
            return

        tag_id = row[0]

        await self.db.execute(query_update, (content, tag_id))
        await ctx.reply(content="Successfully edited tag.", mention_author=False)

    @commands.guild_only()
    @tag.command(name="remove", aliases=["delete"])
    async def tag_remove(
        self,
        ctx: Context,
        *,
        name: Annotated[str, TagName(lower=True)],
    ):
        if ctx.guild is None:
            msg = "ctx.guild is None in guild only command"
            raise RuntimeError(msg)

        bypass_owner_check = (
            ctx.author.id == self.bot.owner_id
            or ctx.author.guild_permissions.manage_messages  # pyright: ignore[reportAttributeAccessIssue]
        )
        clause = "LOWER(name) = ? AND guild_id = ?"

        if bypass_owner_check:
            args = [name, ctx.guild.id]
        else:
            args = [name, ctx.guild.id, ctx.author.id]
            clause += " AND owner_id = ?"

        query = f"DELETE FROM tag_lookup WHERE {clause} RETURNING tag_id"
        cursor = await self.db.execute(query, args)
        row = cursor.fetchone()

        if row is None:
            await ctx.reply(
                content="Could not delete tag. Either it does not exist or you do not have permissions to do so.",
                mention_author=False,
            )
            return

        tag_id: int = row[0]

        args.append(tag_id)
        clause += " AND id = ?"
        query = query = f"DELETE FROM tags WHERE {clause} RETURNING id"
        cursor = await self.db.execute(query, args)
        row = cursor.fetchone()

        if row is None:
            await ctx.reply(
                content="Tag alias successfully deleted.",
                mention_author=False,
            )
        else:
            await ctx.reply(
                content="Tag and corresponding aliases successfully deleted.",
                mention_author=False,
            )

    @commands.guild_only()
    @tag.command(name="raw")
    async def tag_raw(
        self,
        ctx: Context,
        *,
        name: Annotated[str, TagName(lower=True)],
    ):
        query = """
        SELECT tags.content
        FROM tag_lookup
        LEFT JOIN tags ON tags.id = tag_lookup.tag_id
        WHERE tag_lookup.guild_id = ? AND LOWER(tag_lookup.name) = ?
        """

        if ctx.guild is None:
            msg = "ctx.guild is None in guild only command"
            raise RuntimeError(msg)

        cursor = await self.db.execute(query, (ctx.guild.id, name))
        row = cursor.fetchone()

        if row is None:
            await ctx.reply(content="Tag not found.", mention_author=False)
            return

        content = discord.utils.escape_markdown(row[0])
        content = content.replace("<", "\\<")

        if len(content) > 2000:
            fp = io.BytesIO(content.encode())

            await ctx.reply(
                file=discord.File(fp, filename="message_too_long.txt"),
                mention_author=False,
            )
        else:
            await ctx.reply(content=content, mention_author=False)

    @commands.guild_only()
    @tag.command(name="list")
    async def tag_list(self, ctx: Context):
        if ctx.guild is None:
            msg = "ctx.guild is None in guild only command"
            raise RuntimeError(msg)

        view = PaginationView(ctx, TagPageSource(self.db, ctx.guild.id, per_page=10))
        await view.start()


async def setup(bot: "MinimBot"):
    await bot.add_cog(TagsCog(bot))
