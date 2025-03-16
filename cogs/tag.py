from collections.abc import Sequence
import io
from math import ceil
from typing import TYPE_CHECKING, Annotated, override

import aiosqlite
import discord
from discord.ext import commands
from discord.ext.commands import Context

if TYPE_CHECKING:
    from bot import VeryCheapBot


class TagName(commands.clean_content):
    def __init__(self, *, lower: bool = False):
        self.lower = lower
        super().__init__()

    async def convert(self, ctx: Context, argument: str) -> str:
        converted = await super().convert(ctx, argument)
        lower = converted.lower().strip()

        if not lower:
            raise commands.BadArgument("Missing tag name.")

        if len(lower) > 100:
            raise commands.BadArgument("Tag name is a maximum of 100 characters.")

        first_word, _, _ = lower.partition(" ")

        # get tag command.
        root: commands.GroupMixin = ctx.bot.get_command("tag")  # type: ignore
        if first_word in root.all_commands:
            raise commands.BadArgument("This tag name starts with a reserved word.")

        return lower if self.lower else converted.strip()


class TagList(discord.ui.View):
    message: discord.Message

    def __init__(self, ctx: Context, items: Sequence[str]):
        super().__init__(timeout=180)
        self.ctx = ctx
        self.items = items
        
        self.page = 0
        self.per_page = 10
        self.max_page_index = ceil(len(self.items) / self.per_page) - 1

        if self.max_page_index <= 1:
            self.remove_item(self.to_first_page)
            self.remove_item(self.to_last_page)
        if self.max_page_index == 0:
            self.remove_item(self.to_previous_page)
            self.remove_item(self.to_next_page)

    def format_page(self):
        begin = self.page * self.per_page
        end = (self.page + 1) * self.per_page
        description = ""

        for idx, item in enumerate(self.items[begin:end]):
            description += f"`{begin + idx + 1}` {item}\n"

        embed = discord.Embed(
            color=discord.Color.yellow(),
            title="Tag list",
            description=description,
        )
        embed.set_footer(text=f"Page {self.page + 1}/{self.max_page_index + 1}")

        return [embed]

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.edit_message(
            embeds=self.format_page(),
            view=self,
        )

    
    @discord.ui.button(label="<<", style=discord.ButtonStyle.grey, disabled=True)
    async def to_first_page(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ):
        self.page = 0
        await self.callback(interaction)

    @discord.ui.button(label="<", style=discord.ButtonStyle.grey, disabled=True)
    async def to_previous_page(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ):
        self.page -= 1
        await self.callback(interaction)

    @discord.ui.button(label=">", style=discord.ButtonStyle.grey)
    async def to_next_page(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ):
        self.page += 1
        await self.callback(interaction)

    @discord.ui.button(label=">>", style=discord.ButtonStyle.grey)
    async def to_last_page(
        self, interaction: discord.Interaction, _: discord.ui.Button
    ):
        self.page = self.max_page_index
        await self.callback(interaction)


class TagsCog(commands.Cog, name="Tags"):
    def __init__(self, bot: "VeryCheapBot") -> None:
        self.bot = bot

    @override
    async def cog_check(self, ctx: Context) -> bool:
        user_id = ctx.author.id
        role_ids = [str(role.id) for role in ctx.author.roles]
        return (
            str(user_id) in self.bot.cfg["SOCIETY_USER_IDS"]
            or any(x in self.bot.cfg["SOCIETY_ROLE_IDS"] for x in role_ids)
            or (
                isinstance(ctx.author, discord.Member)
                and ctx.author.guild_permissions.administrator
            )
        )
    
    @commands.guild_only()
    @commands.group(name="tag")
    async def tag(self, ctx: Context, *, name: Annotated[str, TagName(lower=True)]):
        query = """
        SELECT tags.content
        FROM tag_lookup
        LEFT JOIN tags ON tags.id = tag_lookup.tag_id
        WHERE tag_lookup.guild_id = ? AND LOWER(tag_lookup.name) = ?
        """

        async with self.bot.db.execute(query, (ctx.guild.id, name)) as cursor:
            row = await cursor.fetchone()

        if row is None:
            await ctx.reply(content="Tag not found.", mention_author=False)
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
        VALUES (?, ?, ?, ?)
        """

        async with self.bot.db.cursor() as cursor:
            try:
                await cursor.execute(
                    tag_create_query,
                    (name, content, ctx.author.id, ctx.guild.id)
                )
            except aiosqlite.IntegrityError:
                await self.bot.db.rollback()
                await ctx.reply(content="This tag already exists.", mention_author=False)
                return
            except aiosqlite.DatabaseError:
                await self.bot.db.rollback()
                await ctx.reply(content="Could not create tag.", mention_author=False)
                return
            
            tag_id_row = await cursor.fetchone()

            if tag_id_row is None:
                await ctx.reply(content="Could not create tag.", mention_author=False)
                return

            tag_id: int = tag_id_row[0]

            try:
                await cursor.execute(
                    tag_lookup_create_query,
                    (name, tag_id, ctx.author.id, ctx.guild.id)
                )
            except aiosqlite.IntegrityError:
                await self.bot.db.rollback()
                await ctx.reply(content="This tag already exists.", mention_author=False)
                return
            except aiosqlite.DatabaseError:
                await self.bot.db.rollback()
                await ctx.reply(content="Could not create tag.", mention_author=False)
                return

            await self.bot.db.commit()
        
        await ctx.reply(content=f"Tag {name} successfully created.", mention_author=False)


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

        async with self.bot.db.execute(query_select, (ctx.guild.id, old_name.lower())) as cursor:
            row = await cursor.fetchone()

            if row is None:
                await ctx.reply(f"A tag with the name of {old_name} does not exist.", mention_author=False)
                return

            tag_id, guild_id = row

        try:
            await self.bot.db.execute(query_insert, (new_name, tag_id, ctx.author.id, guild_id))
            await self.bot.db.commit()
            await ctx.reply(f"Tag alias {new_name} that points to {old_name} successfully created.", mention_author=False)
        except aiosqlite.IntegrityError:
            await self.bot.db.rollback()
            await ctx.reply(content="A tag with this name already exists.", mention_author=False)
            return
        except aiosqlite.DatabaseError:
            await self.bot.db.rollback()
            await ctx.reply(content="Could not create tag alias.", mention_author=False)
            return

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

        async with self.bot.db.execute(query_select, (name, ctx.author.id, ctx.guild.id)) as cursor:
            row = await cursor.fetchone()

            if row is None:
                await ctx.reply(
                    content="Could not find a tag with that name, are you sure it exists or you own it?",
                    mention_author=False,
                )
                return

            tag_id = row[0]

        await self.bot.db.execute(query_update, (content, tag_id))
        await self.bot.db.commit()

        await ctx.reply(content="Successfully edited tag.", mention_author=False)
        

    @commands.guild_only()
    @tag.command(name="remove", aliases=["delete"])
    async def tag_remove(
        self,
        ctx: Context,
        *,
        name: Annotated[str, TagName(lower=True)],
    ):
        bypass_owner_check = (
            ctx.author.id == self.bot.owner_id
            or ctx.author.guild_permissions.manage_messages
        )
        clause = "LOWER(name) = ? AND guild_id = ?"

        if bypass_owner_check:
            args = [name, ctx.guild.id]
        else:
            args = [name, ctx.guild.id, ctx.author.id]
            clause += " AND owner_id = ?"

        query = f"DELETE FROM tag_lookup WHERE {clause} RETURNING tag_id"
        async with self.bot.db.execute(query, args) as cursor:
            row = await cursor.fetchone()

            if row is None:
                await ctx.reply(
                    content="Could not delete tag. Either it does not exist or you do not have permissions to do so.",
                    mention_author=False,
                )
                return
        
            tag_id: int = row[0]
        
        args.append(tag_id)
        clause += " AND id = ?"
        query = query = f"DELETE FROM tags WHERE {clause} RETURNING tag_id"
        async with self.bot.db.execute(query, args) as cursor:
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

        async with self.bot.db.execute(query, (ctx.guild.id, name)) as cursor:
            row = await cursor.fetchone()

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
    async def tag_list(self, ctx: Context, *, member: discord.User | None = None):
        clause = "guild_id = ?"
        args = [ctx.guild.id]

        if member is not None:
            clause += " AND owner_id = ?"
            args.append(member.id)

        query = f"""
        SELECT name
        FROM tag_lookup
        WHERE {clause}
        ORDER BY name
        """

        async with self.bot.db.execute(query, args) as cursor:
            rows = list(await cursor.fetchall())

            if len(rows) == 0:
                if member is not None:
                    await ctx.reply(content=f"{member} has no tags.", mention_author=False)
                else:
                    await ctx.reply(content="This server has no tags.", mention_author=False)

                return

            tag_names: list[str] = [row[0] for row in rows]

        view = TagList(ctx, tag_names)
        view.message = await ctx.reply(
            embeds=view.format_page(),
            view=view,
            mention_author=False,
        )
        

async def setup(bot: "VeryCheapBot"):
    await bot.add_cog(TagsCog(bot))
