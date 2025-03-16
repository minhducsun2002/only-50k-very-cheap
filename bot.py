import logging
import logging.handlers
import asyncio
import sys
from pathlib import Path

import aiosqlite
import discord
from discord.ext import commands
from discord.ext.commands import Bot
from dotenv import dotenv_values


BOT_DIR = Path(__file__).absolute().parent
cfg = dotenv_values(BOT_DIR / ".env")


class VeryCheapBot(Bot):
    cfg: dict[str, str | None]
    db: aiosqlite.Connection

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


async def startup():
    logger = logging.getLogger("discord")
    logger.setLevel(logging.DEBUG)

    handler = logging.handlers.RotatingFileHandler(
        filename="discord.log",
        encoding="utf-8",
        maxBytes=32 * 1024 * 1024,  # 32 MiB
        backupCount=5,  # Rotate through 5 files
    )
    dt_fmt = "%Y-%m-%d %H:%M:%S"
    formatter = logging.Formatter(
        "[{asctime}] [{levelname:<8}] {name}: {message}", dt_fmt, style="{"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    intents = discord.Intents.default()
    intents.message_content = True
    intents.members = True

    bot = VeryCheapBot(command_prefix=commands.when_mentioned_or("l>"), intents=intents)
    bot.cfg = cfg

    for file in (BOT_DIR / "cogs").glob("*.py"):
        cogname = f"cogs.{file.stem}"
        logger = logging.getLogger(cogname)
        logger.setLevel(logging.DEBUG)

        handler = logging.handlers.RotatingFileHandler(
            filename="bot.log",
            encoding="utf-8",
            maxBytes=32 * 1024 * 1024,  # 32 MiB
            backupCount=5,  # Rotate through 5 files
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

        if file.stem in ["hotreload", "botutils", "__init__", "hvn", "luna", "misc"]:
            continue
        try:
            await bot.load_extension(cogname)
            print(f"Loaded {cogname}")
        except Exception as e:
            print(f"Failed to load extension {cogname}")
            print(f"{type(e).__name__}: {e}")

    if (token := cfg.get("TOKEN")) is None:
        sys.exit(
            "[ERROR] Token not found, make sure 'TOKEN' is set in the '.env' file. Exiting."
        )

    async with aiosqlite.connect(BOT_DIR / "data" / "database.sqlite3", autocommit=False) as db:
        bot.db = db

        try:
            await bot.start(token)
        except discord.LoginFailure:
            sys.exit(
                "[ERROR] Token not found, make sure 'TOKEN' is set in the '.env' file. Exiting."
            )
        except discord.PrivilegedIntentsRequired:
            sys.exit(
                "[ERROR] Message Content Intent not enabled, go to 'https://discord.com/developers/applications' and enable the Message Content Intent. Exiting."
            )


if __name__ == "__main__":
    asyncio.run(startup())
