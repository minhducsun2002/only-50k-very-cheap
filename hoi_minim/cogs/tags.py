import io
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, cast, override

import apsw
import discord
from discord.ext import commands
from discord.ext.commands import Context

from hoi_minim.lib import async_apsw
from hoi_minim.lib.pagination import PageSourceProtocol, PaginationView

if TYPE_CHECKING:
    from hoi_minim.bot import MinimBot
    from hoi_minim.cogs.allowlister import AllowlisterCog


class TagPageSource(PageSourceProtocol):
    def __init__(self, db: async_apsw.Connection, guild_id: int, *, per_page: int):
        self.db: async_apsw.Connection = db
        self.guild_id: int = guild_id
        self.per_page: int = per_page

    async def get_count(self):
        query = "SELECT COUNT(id) FROM tags WHERE guild_id = ?"
        result = await self.db.execute(query, (self.guild_id,))
        count: int = await result.get()

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

        return await result.fetchall()

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
        self.allowlister: "AllowlisterCog" = self.bot.get_cog("Allowlister")  # pyright: ignore[reportAttributeAccessIssue]

    @override
    def cog_check(self, ctx: Context["MinimBot"]) -> bool:
        return self.allowlister.is_allowlisted_context(ctx)

    @commands.guild_only()
    @commands.group(name="tag", invoke_without_command=True)
    async def tag(self, ctx: Context, *, name: Annotated[str, TagName(lower=True)]):
        query = """
        SELECT tags.id, tags.content
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

        cursor = await self.bot.db.execute(query, (ctx.guild.id, name))
        row: tuple[int, str] | None = await cursor.fetchone()

        if row is None:
            cursor = await self.bot.db.execute(search_query, (name, ctx.guild.id))
            rows = cast(tuple[str], await cursor.fetchall())
            options = [row[0] for row in rows]

            content = "Tag not found."

            if len(options) > 0:
                content += f" Did you mean...\n{'\n'.join(options)}"

            await ctx.reply(
                content=content,
                mention_author=False,
            )
            return

        await ctx.reply(content=row[1], mention_author=False)

        update_uses_query = """
        UPDATE tags SET uses = uses + 1 WHERE id = ?
        """
        await self.bot.db.execute(update_uses_query, (row[0],))

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

        async with self.bot.db:
            try:
                cursor = await self.bot.db.execute(
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

            tag_id_row: tuple[int] | None = await cursor.fetchone()

            if tag_id_row is None:
                await ctx.reply(content="Could not create tag.", mention_author=False)

                msg = "Missing tag ID row after creation"
                raise Exception(msg)  # noqa: TRY002

            tag_id = tag_id_row[0]

            try:
                cursor = await self.bot.db.execute(
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

        cursor = await self.bot.db.execute(
            query_select, (ctx.guild.id, old_name.lower())
        )
        row: tuple[int, int] | None = await cursor.fetchone()

        if row is None:
            await ctx.reply(
                f"A tag with the name of {old_name} does not exist.",
                mention_author=False,
            )
            return

        tag_id, guild_id = row

        async with self.bot.db:
            try:
                await self.bot.db.execute(
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
        UPDATE tags SET content = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?
        """

        if ctx.guild is None:
            msg = "ctx.guild is None in guild only command"
            raise RuntimeError(msg)

        cursor = await self.bot.db.execute(
            query_select, (name, ctx.author.id, ctx.guild.id)
        )
        row: tuple[int] | None = await cursor.fetchone()

        if row is None:
            await ctx.reply(
                content="Could not find a tag with that name, are you sure it exists or you own it?",
                mention_author=False,
            )
            return

        tag_id = row[0]

        await self.bot.db.execute(query_update, (content, tag_id))
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
        cursor = await self.bot.db.execute(query, args)
        row: tuple[int] | None = await cursor.fetchone()

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
        cursor = await self.bot.db.execute(query, args)
        row = await cursor.fetchone()

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

        cursor = await self.bot.db.execute(query, (ctx.guild.id, name))
        row: tuple[str] | None = await cursor.fetchone()

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

        view = PaginationView(
            ctx, TagPageSource(self.bot.db, ctx.guild.id, per_page=10)
        )
        await view.start()

    @commands.guild_only()
    @tag.command(name="info")
    async def tag_info(
        self, ctx: Context, *, name: Annotated[str, TagName(lower=True)]
    ):
        if ctx.guild is None:
            msg = "ctx.guild is None in guild only command"
            raise RuntimeError(msg)

        query = """
        SELECT
            tag_lookup.name <> tags.name AS "is_alias",
            tag_lookup.name AS lookup_name,
            tag_lookup.created_at AS lookup_created_at,
            tag_lookup.owner_id AS lookup_owner_id,
            tags.name,
            tags.owner_id,
            tags.created_at,
            tags.updated_at,
            tags.uses
        FROM tag_lookup
        LEFT JOIN tags ON tags.id = tag_lookup.tag_id
        WHERE tag_lookup.guild_id = ? AND LOWER(tag_lookup.name) = ?
        """

        cursor = await self.bot.db.execute(query, (ctx.guild.id, name))
        row: (
            tuple[bool, str, str, int, str, int, str, str, int] | None
        ) = await cursor.get()

        if row is None:
            await ctx.reply(content="Tag not found.", mention_author=False)
            return

        (
            is_alias,
            lookup_name,
            lookup_created_at,
            lookup_owner_id,
            name,
            owner_id,
            created_at,
            updated_at,
            uses,
        ) = row

        if is_alias:
            embed = discord.Embed(
                color=discord.Color.yellow(),
                title=lookup_name,
                timestamp=datetime.fromisoformat(lookup_created_at).replace(tzinfo=UTC),
            )

            user = self.bot.get_user(lookup_owner_id) or (
                await self.bot.fetch_user(lookup_owner_id)
            )
            embed.set_author(name=str(user), icon_url=user.display_avatar.url)

            embed.add_field(name="Owner", value=f"<@{owner_id}>")
            embed.add_field(name="Original", value=name)
        else:
            embed = discord.Embed(
                color=discord.Color.yellow(),
                title=name,
                timestamp=datetime.fromisoformat(created_at).replace(tzinfo=UTC),
            )

            user = self.bot.get_user(owner_id) or (await self.bot.fetch_user(owner_id))
            embed.set_author(name=str(user), icon_url=user.display_avatar.url)

            embed.add_field(name="Owner", value=f"<@{owner_id}>")
            embed.add_field(name="Uses", value=str(uses))

            if updated_at != created_at:
                updated_timestamp = int(
                    datetime.fromisoformat(updated_at).replace(tzinfo=UTC).timestamp()
                )
                embed.add_field(name="Last edited", value=f"<t:{updated_timestamp}:R>")

        await ctx.reply(embed=embed, mention_author=False)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if (
            not self.allowlister.is_allowlisted_id(message.author.id)
            or message.channel.id not in self.allowlister.thread_ids
        ):
            return

        if message.author.bot:
            return

        if message.webhook_id:
            return

        if not message.guild:
            return

        if message.content.startswith("... "):
            fake_command = (
                f"{self.bot.user.mention} tag {message.content.removeprefix('... ')}"
            )
        elif message.content.startswith("… "):
            fake_command = (
                f"{self.bot.user.mention} tag {message.content.removeprefix('… ')}"
            )
        elif message.content.startswith(".. "):
            fake_command = (
                f"{self.bot.user.mention} tag add {message.content.removeprefix('.. ')}"
            )
        else:
            return

        message.content = fake_command
        ctx = await self.bot.get_context(message)

        await self.bot.invoke(ctx)


async def setup(bot: "MinimBot"):
    await bot.add_cog(TagsCog(bot))
