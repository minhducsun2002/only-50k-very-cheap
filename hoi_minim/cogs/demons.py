import asyncio
import tempfile
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, override
from zoneinfo import ZoneInfo

import discord
import structlog
import typst
from aiohttp import web
from discord.ext import commands, tasks
from discord.ext.commands import Context
from discord.http import Route
from discord.utils import _from_json, escape_markdown

from hoi_minim.lib.pagination import PageSourceProtocol, PaginationView
from hoi_minim.settings import settings

if TYPE_CHECKING:
    from hoi_minim.bot import MinimBot
    from hoi_minim.cogs.allowlister import AllowlisterCog
    from hoi_minim.cogs.database import DatabaseCog

RESOURCE_DIR = Path(__file__).parent.parent.parent / "resources"
VTUBER_TEMPLATES = {
    "termination": RESOURCE_DIR / "termination.typ",
    "graduation": RESOURCE_DIR / "graduation.typ",
}

logger: structlog.stdlib.BoundLogger = structlog.get_logger()
router = web.RouteTableDef()


@router.post("/confessions")
async def confessions(request: web.Request) -> web.Response:
    bot: "MinimBot" = request.config_dict["bot"]
    thread_id: int = request.config_dict["thread_id"]
    channel = bot.get_channel(thread_id)
    if channel is None:
        channel = await bot.fetch_channel(thread_id)

    content_type = request.headers.get("Content-Type")
    if content_type == "application/json":
        params = await request.json(loads=_from_json)
    elif content_type in ["application/x-www-form-urlencoded", "multipart/form-data"]:
        params = await request.post()
    else:
        await logger.aerror("received invalid content-type", content_type=content_type)
        raise web.HTTPBadRequest(reason="Invalid Content-Type")

    if "timestamp" not in params or "content" not in params or "index" not in params:
        await logger.aerror("missing params", params=params)
        raise web.HTTPBadRequest(reason="Missing parameters")

    timestamp = params["timestamp"]
    content = params["content"]
    index = params["index"]

    if (
        not isinstance(timestamp, str)
        or not isinstance(content, str)
        or not isinstance(index, (str, int))
    ):
        await logger.aerror("invalid params", params=params)
        raise web.HTTPBadRequest(reason="Invalid parameters")

    try:
        parsed_timestamp = datetime.fromisoformat(timestamp)
    except ValueError as e:
        await logger.aerror("invalid timestamp", timestamp=timestamp)
        raise web.HTTPBadRequest(reason="Invalid timestamp") from e

    embed = discord.Embed(
        title=f"confession #{index}",
        description=escape_markdown(content),
        timestamp=parsed_timestamp,
    )

    await channel.send(embed=embed)

    raise web.HTTPNoContent


async def on_response_prepare(_: web.Request, response: web.StreamResponse):
    response.headers.add("x-content-type-options", "nosniff")
    if response.headers.get("server"):
        del response.headers["server"]


class ThreadNameConverter(commands.clean_content):
    def __init__(self) -> None:
        super().__init__(
            fix_channel_mentions=True, use_nicknames=True, remove_markdown=True
        )

    @override
    async def convert(self, ctx: Context["MinimBot"], argument: str) -> str:
        argument = await super().convert(ctx, argument)

        if len(argument) > 100:
            msg = "Thread name too long."
            raise commands.BadArgument(msg)

        return argument


class ThreadPageSource(PageSourceProtocol):
    def __init__(self, db: "DatabaseCog", *, per_page: int):
        self.db: "DatabaseCog" = db
        self.per_page: int = per_page

    async def get_count(self):
        query = "SELECT COUNT(id) FROM thread_name_queue WHERE thread_id IS NULL"
        result = await self.db.execute(query)
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
        query = "SELECT id, thread_name, owner_id FROM thread_name_queue WHERE thread_id IS NULL ORDER BY id LIMIT 10 OFFSET ?"
        offset = page_number * self.per_page
        result = await self.db.execute(query, (offset,))

        return result.fetchall()

    @override
    async def format_page(
        self, menu: "PaginationView", page: list[tuple[int, str, int]]
    ) -> discord.Embed:
        description = ""

        for thread in page:
            description += f"`{thread[0]}` {thread[1]} - <@{thread[2]}>\n"

        return discord.Embed(
            color=discord.Color.yellow(),
            title="Thread list",
            description=description,
        )


class DemonsCog(commands.Cog, name="Demons"):
    def __init__(self, bot: "MinimBot") -> None:
        self.bot: "MinimBot" = bot
        self.db: "DatabaseCog" = self.bot.get_cog("Database")  # pyright: ignore[reportAttributeAccessIssue]
        self.allowlister: "AllowlisterCog" = self.bot.get_cog("Allowlister")  # pyright: ignore[reportAttributeAccessIssue]

        self.web_app: web.Application | None = None
        self.web_app_task: asyncio.Task[None] | None = None

        if settings.nsfw_channel_id is None:
            msg = "Missing NSFW channel ID"
            raise ValueError(msg)

    @override
    def cog_check(self, ctx: Context["MinimBot"]) -> bool:
        return self.allowlister.is_allowlisted_context(ctx)

    @override
    async def cog_load(self) -> None:
        self.queue_loop.start()

        if thread_id := settings.confessions_channel_id:
            self.web_app = web.Application()
            self.web_app.on_response_prepare.append(on_response_prepare)

            self.web_app.add_routes(router)

            self.web_app["bot"] = self.bot
            self.web_app["thread_id"] = thread_id

            self.web_app_task = asyncio.ensure_future(
                web._run_app(
                    self.web_app,
                    port=6969,
                    host="0.0.0.0",
                )
            )

    @override
    async def cog_unload(self) -> None:
        self.queue_loop.stop()

        if self.web_app is not None:
            await self.web_app.shutdown()
            await self.web_app.cleanup()

    @commands.command(name="toggleinvite", aliases=["tinvite"])
    @commands.check_any(
        commands.has_guild_permissions(manage_threads=True),
        commands.is_owner(),
    )
    async def toggleinvite(self, ctx: Context, enabled: bool | None = None):
        if not isinstance(ctx.channel, discord.Thread):
            msg = "This command can only be used in threads."
            raise commands.errors.CheckFailure(msg)

        new_invitable = not ctx.channel.invitable if enabled is None else enabled

        await self.bot.http.request(
            Route("PATCH", "/channels/{thread_id}", thread_id=ctx.channel.id),
            json={"invitable": new_invitable},
        )

        await ctx.reply(f'Set "Anyone can invite" to {new_invitable} for this thread.')

    @commands.command(name="termination")
    async def termination(self, ctx: Context, vtuber_name: str, company_name: str):
        await self._vtuber_copypasta(ctx, vtuber_name, company_name)

    @commands.command("graduation")
    async def graduation(self, ctx: Context, vtuber_name: str, company_name: str):
        await self._vtuber_copypasta(ctx, vtuber_name, company_name)

    async def _vtuber_copypasta(
        self, ctx: Context, vtuber_name: str, company_name: str
    ):
        if ctx.command is None:
            raise TypeError

        with tempfile.TemporaryDirectory() as tmpdir:
            inp = Path(tmpdir) / f"{ctx.command.name}.typ"
            out = Path(tmpdir) / f"{ctx.command.name}.png"

            with (
                VTUBER_TEMPLATES[ctx.command.name].open("r", encoding="utf-8") as ft,
                inp.open("w", encoding="utf-8") as f,
            ):
                template = ft.read()

                f.write(
                    template.replace("%%NAME%%", vtuber_name).replace(
                        "%%COMPANY_NAME%%", company_name
                    )
                )

            await asyncio.to_thread(
                typst.compile, str(inp), output=str(out), format="png", ppi=144.0
            )

            discord_file = discord.File(out, filename=f"{ctx.command.name}.png")

            await ctx.reply(file=discord_file, mention_author=False)

    @commands.command("capology")
    async def cimpher_apology(
        self,
        ctx: Context,
        target: Annotated[str, commands.clean_content],
        mistake: Annotated[str, commands.clean_content],
    ):
        await ctx.reply(
            f"""chẹp, sorry mn vì noti nổ tùm lum cả tối nay 😇

cá nhân mình và {target} vừa xảy ra một số lùm xùm có lẽ là không đáng có dẫn đến ẩu đả và cãi nhau rất nhiều, nhưng sau khi chửi nhau mỏi miệng thì cái gì cũng phải đến hồi kết và lựa chọn của 2 đứa là post bài hòa giải và ngừng dây dưa đến nhau

về bản thân mình thì mình xin nhận lỗi vì đã {mistake}, cái này mình thì nghiêm túc xin lỗi và nhận hoàn toàn trách nhiệm về mình, không mong đc bỏ qua nhưng sẽ rút kinh nghiệm cho sau này

và cũng mong đối phương sẽ ko đả động hay gây ảnh hưởng gì đến các mqh cx như đời sống của mình vì đây hoàn toàn là chuyện cá nhân, cảm ơn đã đọc""",
            mention_author=False,
        )

    @commands.command(name="everyone")
    async def everyone(self, ctx: Context):
        await ctx.reply(
            "@everyone",
            mention_author=False,
            allowed_mentions=discord.AllowedMentions.all(),
        )

    @commands.command(name="here")
    async def here(self, ctx: Context):
        await ctx.reply(
            "@here",
            mention_author=False,
            allowed_mentions=discord.AllowedMentions.all(),
        )

    @commands.guild_only()
    @commands.group(name="queue", invoke_without_command=True)
    async def queue(self, ctx: Context):
        pass

    @queue.command("add")
    async def queue_add(
        self, ctx: Context, *, thread_name: Annotated[str, ThreadNameConverter]
    ):
        await self.db.execute(
            "INSERT INTO thread_name_queue (thread_name, owner_id) VALUES (?, ?)",
            (thread_name, ctx.author.id),
        )

        return await ctx.reply("Added to queue.", mention_author=False)

    @queue.command("remove")
    async def queue_remove(self, ctx: Context, *, thread_name_or_id: str):
        bypass_owner_check = (
            ctx.author.id == self.bot.owner_id
            or ctx.author.guild_permissions.manage_threads  # pyright: ignore[reportAttributeAccessIssue]
        )

        if bypass_owner_check:
            clause = "thread_name = ? OR id = ?"
            args = [thread_name_or_id, thread_name_or_id]
        else:
            clause = "(thread_name = ? OR id = ?) AND owner_id = ?"
            args = [thread_name_or_id, thread_name_or_id, ctx.author.id]

        cursor = await self.db.execute(
            f"SELECT id FROM thread_name_queue WHERE {clause}", args
        )
        thread_id = cursor.get

        if thread_id is None:
            await ctx.reply(
                "Thread name not in queue, or you don't have permission to remove it.",
                mention_author=False,
            )
            return

        await self.db.execute(
            "DELETE FROM thread_name_queue WHERE id = ?", (thread_id,)
        )
        await ctx.reply("Removed from queue.", mention_author=False)

    @queue.command("list")
    async def queue_list(self, ctx: Context):
        source = ThreadPageSource(self.db, per_page=10)
        view = PaginationView(ctx, source)

        await view.start()

    @queue.command("invited")
    async def queue_invited(self, ctx: Context):
        await ctx.reply(
            embed=discord.Embed(
                title="Invited people",
                description=self.allowlister.get_allowlisted_mentions(),
            ),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @queue.command("clear")
    @commands.check_any(
        commands.has_guild_permissions(manage_threads=True),
        commands.is_owner(),
    )
    async def queue_clear(self, ctx: Context):
        await self.db.execute("DELETE FROM thread_name_queue")

        await ctx.reply("Cleared queue.", mention_author=False)

    @queue.command("nuke")
    @commands.check_any(
        commands.has_guild_permissions(manage_threads=True),
        commands.is_owner(),
    )
    async def queue_nuke(self, ctx: Context):
        await ctx.channel.delete()

    async def _cleanup_old_threads(self):
        cursor = await self.db.execute(
            "SELECT id, thread_id, created WHERE thread_id IS NOT NULL and deleted = FALSE"
        )
        existing_channels = cursor.fetchall()

        for channel in existing_channels:
            (id, thread_id, created_at) = channel
            created_at = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=UTC
            )

            if datetime.now(UTC) - created_at >= timedelta(days=1):
                channel = self.bot.get_channel(thread_id)

                if channel is not None:
                    await channel.delete()

                await self.db.execute(
                    "UPDATE thread_name_queue SET deleted = TRUE WHERE id = ?", (id,)
                )

    async def _create_new_thread(self, id: int | None = None):
        nsfw_channel = self.bot.get_channel(settings.nsfw_channel_id)

        if nsfw_channel is None:
            await logger.aerror("nsfw channel not found", id=settings.nsfw_channel_id)
            return

        if not isinstance(nsfw_channel, discord.TextChannel):
            await logger.aerror(
                "nsfw channel not a text channel",
                id=nsfw_channel.id,
                name=nsfw_channel.name
                if not isinstance(nsfw_channel, discord.abc.PrivateChannel)
                else "dms",
            )
            return

        await logger.ainfo("fetching new thread for creation", id=id)

        clause = "thread_id IS NULL AND deleted = FALSE"
        args = None

        if id is not None:
            clause += " AND id = ?"
            args = [id]

        cursor = await self.db.execute(
            f"SELECT id, thread_name FROM thread_name_queue WHERE {clause}", args
        )
        result = cursor.get

        if result is None:
            await logger.aerror("ran out of threads")
            return

        (id, thread_name) = result

        await logger.ainfo("creating thread", thread_name=thread_name)
        thread = await nsfw_channel.create_thread(
            name=f"[Hội Nghĩa] {thread_name}",
            type=discord.ChannelType.private_thread,
            invitable=True,
        )

        await logger.ainfo("created thread", thread_id=thread.id)

        await logger.ainfo("inviting members")
        await thread.send(self.allowlister.get_allowlisted_mentions())

        await logger.ainfo("disabling thread invites")
        await self.bot.http.request(
            Route("PATCH", "/channels/{thread_id}", thread_id=thread.id),
            json={"invitable": False},
        )

        await logger.info("marking thread as created")
        await self.db.execute(
            "UPDATE thread_name_queue SET thread_id = ?, created = CURRENT_TIMESTAMP WHERE id = ?",
            (thread.id, id),
        )

    @queue.command("create")
    @commands.check_any(
        commands.has_guild_permissions(manage_guild=True),
        commands.is_owner(),
    )
    async def queue_create(self, ctx: Context, id: int | None = None):
        await self._cleanup_old_threads()
        await self._create_new_thread(id=id)

    @tasks.loop(time=[time(hour=0, minute=0, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))])
    async def queue_loop(self):
        await logger.ainfo("executing queue creation task")

        await self._cleanup_old_threads()
        await self._create_new_thread()


async def setup(bot: "MinimBot"):
    await bot.add_cog(DemonsCog(bot))
