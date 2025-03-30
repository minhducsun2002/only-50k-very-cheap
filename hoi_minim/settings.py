from pathlib import Path
from typing import ClassVar

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = {
        "env_prefix": "HOI_MINIM_",
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }

    database_path: Path = Path(__file__).parent.parent / "data" / "database.sqlite3"
    discord_token: str
    confessions_channel_id: int | None = None
    nsfw_channel_id: int | None = None


settings = Settings()  # pyright: ignore[reportCallIssue]
