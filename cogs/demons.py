import asyncio
import tempfile
from datetime import UTC, time, datetime, timedelta
from typing import Annotated, override
from zoneinfo import ZoneInfo
from pathlib import Path

import discord
import typst
from aiohttp import web
from discord.http import Route
from discord.ext import commands, tasks
from discord.ext.commands import Context
from discord.utils import _from_json, escape_markdown

from bot import VeryCheapBot
from cogs.tag import TagList

RESOURCE_DIR = Path(__file__).parent.parent / "resources"
VTUBER_TEMPLATES = {
    "termination": RESOURCE_DIR / "termination.typ",
    "graduation": RESOURCE_DIR / "graduation.typ",
}

router = web.RouteTableDef()


@router.post("/confessions")
async def confessions(request: web.Request) -> web.Response:
    bot: VeryCheapBot = request.config_dict["bot"]
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
        raise web.HTTPBadRequest(reason="Invalid Content-Type")

    if "timestamp" not in params or "content" not in params or "index" not in params:
        raise web.HTTPBadRequest(reason="Missing parameters")

    timestamp = params["timestamp"]
    content = params["content"]
    index = params["index"]

    if (
        not isinstance(timestamp, str)
        or not isinstance(content, str)
        or not isinstance(index, (str, int))
    ):
        raise web.HTTPBadRequest(reason="Invalid parameters")

    try:
        parsed_timestamp = datetime.fromisoformat(timestamp)
    except ValueError:
        raise web.HTTPBadRequest(reason="Invalid timestamp")

    embed = discord.Embed(
        title=f"confession #{index}",
        description=escape_markdown(content),
        timestamp=parsed_timestamp,
    )

    asyncio.create_task(channel.send(embed=embed))

    raise web.HTTPNoContent


async def on_response_prepare(_: web.Request, response: web.StreamResponse):
    response.headers.add("x-content-type-options", "nosniff")
    if response.headers.get("server"):
        del response.headers["server"]


class ThreadNameConverter(commands.clean_content):
    def __init__(self) -> None:
        super().__init__(
            fix_channel_mentions=True,
            use_nicknames=True,
            remove_markdown=True
        )

    @override
    async def convert(self, ctx: Context[VeryCheapBot], argument: str) -> str:
        argument = await super().convert(ctx, argument)

        if len(argument) > 100:
            raise commands.BadArgument("Thread name too long.")

        return argument


class DemonsCog(commands.Cog, name="Demons", command_attrs=dict(hidden=True)):
    def __init__(self, bot: VeryCheapBot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.queue_loop.start()

        if str_thread_id := self.bot.cfg.get("CONFESSIONS_CHANNEL_ID"):
            thread_id = int(str_thread_id)

            self.web_app = web.Application()
            self.web_app.on_response_prepare.append(on_response_prepare)

            self.web_app.add_routes(router)

            self.web_app["bot"] = self.bot
            self.web_app["thread_id"] = thread_id

            _ = asyncio.ensure_future(
                web._run_app(
                    self.web_app,
                    port=6969,
                    host="0.0.0.0",
                )
            )

    async def cog_unload(self) -> None:
        self.queue_loop.stop()

        if hasattr(self, "web_app"):
            await self.web_app.shutdown()
            await self.web_app.cleanup()

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


    @commands.command(name="toggleinvite", aliases=["tinvite"])
    @commands.check_any(
        commands.has_guild_permissions(manage_messages=True),
        commands.is_owner()
    )
    async def toggleinvite(self, ctx: Context, enabled: bool | None = None):
        if not isinstance(ctx.channel, discord.Thread):
            raise commands.errors.CheckFailure(
                "This command can only be used in threads."
            )

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

    @commands.command("capology")
    async def cimpher_apology(self, ctx: Context, target: str, mistake: str):
        await ctx.reply(
            f"""chẹp, sorry mn vì noti nổ tùm lum cả tối nay 😇

cá nhân mình và {escape_markdown(target)} vừa xảy ra một số lùm xùm có lẽ là không đáng có dẫn đến ẩu đả và cãi nhau rất nhiều, nhưng sau khi chửi nhau mỏi miệng thì cái gì cũng phải đến hồi kết và lựa chọn của 2 đứa là post bài hòa giải và ngừng dây dưa đến nhau 

về bản thân mình thì mình xin nhận lỗi vì đã {escape_markdown(mistake)}, cái này mình thì nghiêm túc xin lỗi và nhận hoàn toàn trách nhiệm về mình, không mong đc bỏ qua nhưng sẽ rút kinh nghiệm cho sau này

và cũng mong đối phương sẽ ko đả động hay gây ảnh hưởng gì đến các mqh cx như đời sống của mình vì đây hoàn toàn là chuyện cá nhân, cảm ơn đã đọc""",
            mention_author=False,
        )

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

    @commands.group(name="queue", invoke_without_command=True)
    async def queue(self, ctx: Context):
        pass

    @queue.command("add")
    async def queue_add(self, ctx: Context, *, thread_name: Annotated[str, ThreadNameConverter]):
        await self.bot.db.execute(
            "INSERT INTO thread_name_queue (thread_name, owner_id) VALUES (?, ?)",
            (thread_name, ctx.author.id),
        )
        await self.bot.db.commit()

        return await ctx.reply("Added to queue.", mention_author=False)

    @queue.command("remove")
    async def queue_remove(self, ctx: Context, *, thread_name_or_id: str):
        async with self.bot.db.execute(
            "SELECT * FROM thread_name_queue WHERE (thread_name = :id OR id = CAST(:id AS INTEGER)) AND owner_id = :owner_id",
            {"id": thread_name_or_id, "owner_id": ctx.author.id},
        ) as cursor:
            if not await cursor.fetchone():
                return ctx.reply(
                    "Thread name not in queue, or you don't have permission to remove it.",
                    mention_author=False,
                )

        await self.bot.db.execute(
            "DELETE FROM thread_name_queue WHERE (thread_name = :id OR id = CAST(:id AS INTEGER)) AND owner_id = :owner_id",
            {"id": thread_name_or_id, "owner_id": ctx.author.id},
        )
        await self.bot.db.commit()

        return await ctx.reply("Removed from queue.", mention_author=False)

    @queue.command("list")
    async def queue_list(self, ctx: Context):
        rows = await self.bot.db.execute_fetchall(
            "SELECT * FROM thread_name_queue WHERE thread_id IS NULL AND deleted = FALSE"
        )

        view = TagList(
            ctx,
            [f"`{row[0]}` - {row[1]} - <@{row[2]}>" for row in rows],
        )
        view.message = await ctx.reply(
            embeds=view.format_page(),
            view=view,
            mention_author=False,
        )

    @queue.command("invited")
    async def queue_invited(self, ctx: Context):
        description = ""

        for user in self.bot.cfg["SOCIETY_USER_IDS"].split(" "):
            description += f"<@{user}> "

        for role in self.bot.cfg["SOCIETY_ROLE_IDS"].split(" "):
            description += f"<@&{role}> "

        return await ctx.reply(
            embed=discord.Embed(
                title="Invited people",
                description=description,
            ),
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @queue.command("create")
    @commands.check_any(
        commands.has_permissions(manage_guild=True),
        commands.is_owner(),
    )
    async def queue_create(self, ctx: Context, id: int | None = None):
        await self.queue_loop(cleanup_old_threads=False, id=id)

    @queue.command("clear")
    @commands.check_any(
        commands.has_permissions(manage_guild=True),
        commands.is_owner(),
    )
    async def queue_clear(self, ctx: Context):
        await self.bot.db.execute("DELETE FROM thread_name_queue")
        await self.bot.db.commit()

        return await ctx.reply("Cleared queue.", mention_author=False)

    @queue.command("nuke")
    @commands.check_any(
        commands.has_permissions(manage_threads=True),
        commands.is_owner(),
    )
    async def queue_nuke(self, ctx: Context):
        await ctx.channel.delete()

    @tasks.loop(time=[time(hour=0, minute=0, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))])
    async def queue_loop(self, *, cleanup_old_threads: bool = True, id: int | None = None):
        # Clean up old threads
        if cleanup_old_threads:
            async with self.bot.db.execute(
                "SELECT * FROM thread_name_queue WHERE thread_id IS NOT NULL AND deleted = FALSE"
            ) as cursor:
                stale_channels = await cursor.fetchall()

                for stale_channel in stale_channels:
                    (id, thread_name, _, thread_id, created, _) = stale_channel
                    created_time = datetime.strptime(
                        created, "%Y-%m-%d %H:%M:%S"
                    ).replace(tzinfo=UTC)

                    if datetime.now(UTC) - created_time >= timedelta(days=1):
                        channel = self.bot.get_channel(thread_id)

                        if channel is not None:
                            await channel.delete()

                        await self.bot.db.execute(
                            "UPDATE thread_name_queue SET deleted = TRUE WHERE id = ?",
                            (id,),
                        )

                await self.bot.db.commit()

        nsfw_channel = self.bot.get_channel(int(self.bot.cfg["NSFW_CHANNEL_ID"]))
        if nsfw_channel is None or not isinstance(nsfw_channel, discord.TextChannel):
            return

        clause = "thread_id IS NULL AND deleted = FALSE"
        args = []

        if id is not None:
            clause += " AND id = ?"
            args.append(id)

        async with self.bot.db.execute(
            f"SELECT * FROM thread_name_queue WHERE {clause}", args
        ) as cursor:
            row = await cursor.fetchone()
            if row is None:
                return
            else:
                (id, thread_name, _, _, _, _) = row

        thread = await nsfw_channel.create_thread(
            name=f"[Hội Thanh Hóa] {thread_name}",
            type=discord.ChannelType.private_thread,
            invitable=True,
        )
        message = ""

        for user in self.bot.cfg["SOCIETY_USER_IDS"].split(" "):
            message += f"<@{user}> "

        for role in self.bot.cfg["SOCIETY_ROLE_IDS"].split(" "):
            message += f"<@&{role}> "

        await thread.send(message)
        await self.bot.http.request(
            Route("PATCH", "/channels/{thread_id}", thread_id=thread.id),
            json={"invitable": False},
        )

        if id is not None:
            await self.bot.db.execute(
                "UPDATE thread_name_queue SET thread_id = ?, created = CURRENT_TIMESTAMP WHERE id = ?",
                (
                    thread.id,
                    id,
                ),
            )
            await self.bot.db.commit()
    
    @commands.Cog.listener()
    async def on_thread_member_join(self, member: discord.ThreadMember):
        nsfw_channel_id = int(self.bot.cfg["NSFW_CHANNEL_ID"])  # pyright: ignore[reportArgumentType]

        # Check if the parent of the thread being joined is the NSFW channel
        if member.thread.parent_id != nsfw_channel_id:
            return

        # Check if the thread is one we manage
        async with self.bot.db.execute(
            "SELECT * FROM thread_name_queue WHERE thread_id = ?",
            (member.thread_id,),
        ) as cursor:
            row = await cursor.fetchone()

            # some auxiliary threads we handle
            if row is None and member.thread_id not in {
                1311944713355526174,  # food
                1156264191154475109,  # confessions
                1202627339515592704,  # archive
                1173190577257447575,  # code
                1325871617850609686,  # old demon threads
                1277673920996180079,
                1326243164067069955,
            }:
                return
        
        if str(member.id) not in self.bot.cfg["SOCIETY_USER_IDS"]:
            # if we can't get the guild object to fetch the member,
            # just kick it
            if member.thread.parent is None:
                await member.thread.remove_user(member)
                return

            # check if the user has a whitelisted role (primarily bots)
            guild = member.thread.parent.guild
            full_member = guild.get_member(member.id)

            if full_member is None:
                full_member = await guild.fetch_member(member.id)

            if full_member.guild_permissions.administrator:
                return

            if all(
                str(x.id) not in self.bot.cfg["SOCIETY_ROLE_IDS"]
                for x in full_member.roles
            ):
                await member.thread.remove_user(member)
                


    # @commands.Cog.listener()
    # async def on_presence_update(self, before: discord.Member, after: discord.Member):
    #     if (
    #         (activity := after.activity) is None
    #         or not isinstance(activity, Game)
    #         or activity.start is None
    #     ):
    #         return

    #     if activity.name == "League of Legends" and datetime.now(
    #         UTC
    #     ) - activity.start >= timedelta(minutes=30):
    #         await after.guild.ban(after, reason="Playing League of Legends")


async def setup(bot: VeryCheapBot):
    if bot.cfg.get("NSFW_CHANNEL_ID"):
        await bot.add_cog(DemonsCog(bot))
