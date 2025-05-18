import re
from functools import cached_property
from pathlib import Path
from typing import final

import apsw
import structlog

MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"
MIGRATION_FILE_RE = re.compile(r"v(?P<version>\d+)__(?P<description>.+)\.sql")

logger: structlog.stdlib.BoundLogger = structlog.get_logger()


@final
class Revision:
    __slots__ = ("description", "file", "version")

    def __init__(self, *, version: int, description: str, file: Path) -> None:
        self.version: int = version
        self.description: str = description
        self.file: Path = file

    @classmethod
    def from_match(cls, match: re.Match[str], file: Path):
        return cls(
            version=int(match.group("version")),
            description=match.group("description"),
            file=file,
        )


class Migrator:
    def __init__(self, migrations_dir: Path = MIGRATIONS_DIR) -> None:
        self.migrations_dir: Path = migrations_dir
        self.revisions: dict[int, Revision] = self.get_revisions()

    def get_revisions(self):
        revisions: dict[int, Revision] = {}

        for file in self.migrations_dir.iterdir():
            match = MIGRATION_FILE_RE.match(file.name)

            if match is None:
                continue

            revision = Revision.from_match(match, file)
            revisions[revision.version] = revision

        return revisions

    @cached_property
    def ordered_revisions(self):
        return sorted(self.revisions.values(), key=lambda r: r.version)

    def upgrade(self, connection: apsw.Connection):
        current_version: int = connection.pragma("user_version")
        next_version = current_version

        with connection:
            for revision in self.ordered_revisions:
                if revision.version <= current_version:
                    continue

                logger.info(
                    "applying migration",
                    version=revision.version,
                    name=revision.description,
                )

                _ = connection.execute(revision.file.read_text(encoding="utf-8"))
                next_version = revision.version

        self.stamp(connection, next_version)

    def stamp(self, connection: apsw.Connection, version: int):
        connection.pragma("user_version", version)
