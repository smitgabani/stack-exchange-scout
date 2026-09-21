"""Challenge formats, and the link checking that keeps resources honest.

A format is a named selection of blocks. There is always an effective one: if
nothing is stored, the six core blocks are used, which is exactly the shape
every challenge had before formats existed.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.challenge_format import ChallengeFormat
from app.services import block_service, challenge_blocks

logger = logging.getLogger(__name__)

LINK_TIMEOUT_SECONDS = 6.0
MAX_LINK_CHECKS = 12


class FormatError(RuntimeError):
    """A format was rejected before it could be stored."""


@dataclass
class ActiveFormat:
    name: str
    blocks: list[challenge_blocks.Block]

    @property
    def keys(self) -> list[str]:
        return [block.key for block in self.blocks]


# The name the core blocks go by when nothing is stored. The blocks themselves
# are no longer a module constant: their instructions are overridable, so the
# effective default has to be read per call rather than frozen at import.
DEFAULT_FORMAT_NAME = "Standard"


async def get_default(db: AsyncSession) -> ActiveFormat:
    row = await db.scalar(select(ChallengeFormat).where(ChallengeFormat.is_default))
    if row is None:
        # Still resolved through the database: the default format is the core
        # blocks, and their instructions are overridable like any other.
        return ActiveFormat(
            name=DEFAULT_FORMAT_NAME, blocks=await block_service.resolve(db, None)
        )
    return ActiveFormat(name=row.name, blocks=await block_service.resolve(db, row.blocks))


async def get_by_id(db: AsyncSession, format_id: int) -> ActiveFormat | None:
    row = await db.get(ChallengeFormat, format_id)
    if row is None:
        return None
    return ActiveFormat(name=row.name, blocks=await block_service.resolve(db, row.blocks))


async def resolve_for_run(db: AsyncSession, format_id: int | None) -> ActiveFormat:
    """The format a generation should use: the one asked for, else the default."""
    if format_id is None:
        return await get_default(db)
    chosen = await get_by_id(db, format_id)
    if chosen is None:
        raise FormatError("That format no longer exists.")
    return chosen


async def list_formats(db: AsyncSession) -> list[ChallengeFormat]:
    return list(await db.scalars(select(ChallengeFormat).order_by(ChallengeFormat.name)))


async def _validate(db: AsyncSession, name: str, blocks: list[str]) -> tuple[str, list[str]]:
    name = (name or "").strip()
    if not name:
        raise FormatError("A format needs a name.")
    if len(name) > 80:
        raise FormatError("That name is too long.")

    # Both halves of the library count: a format may name a block the user
    # defined just as readily as one that ships in the code.
    known = await block_service.known_keys(db)
    unknown = [key for key in blocks if key not in known]
    if unknown:
        raise FormatError(f"Unknown block(s): {', '.join(unknown)}")

    # Core blocks are implicit, so they are stripped rather than rejected —
    # a format that lists them is expressing the same thing as one that does not.
    optional = [k for k in blocks if k not in challenge_blocks.CORE_KEYS]
    return name, optional


async def create(
    db: AsyncSession,
    *,
    name: str,
    blocks: list[str],
    description: str | None = None,
    make_default: bool = False,
) -> ChallengeFormat:
    name, optional = await _validate(db, name, blocks)

    existing = await db.scalar(select(ChallengeFormat).where(ChallengeFormat.name == name))
    if existing is not None:
        raise FormatError(f"A format called “{name}” already exists.")

    first = (await db.scalar(select(ChallengeFormat).limit(1))) is None
    if make_default or first:
        await db.execute(
            update(ChallengeFormat).values(is_default=False).where(ChallengeFormat.is_default)
        )

    row = ChallengeFormat(
        name=name,
        description=description,
        blocks=optional,
        is_default=make_default or first,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def update_format(
    db: AsyncSession, format_id: int, *, name: str, blocks: list[str], description: str | None
) -> ChallengeFormat | None:
    row = await db.get(ChallengeFormat, format_id)
    if row is None:
        return None
    name, optional = await _validate(db, name, blocks)

    clash = await db.scalar(
        select(ChallengeFormat).where(ChallengeFormat.name == name, ChallengeFormat.id != format_id)
    )
    if clash is not None:
        raise FormatError(f"A format called “{name}” already exists.")

    row.name = name
    row.blocks = optional
    row.description = description
    await db.commit()
    await db.refresh(row)
    return row


async def set_default(db: AsyncSession, format_id: int) -> ChallengeFormat | None:
    row = await db.get(ChallengeFormat, format_id)
    if row is None:
        return None
    await db.execute(
        update(ChallengeFormat).values(is_default=False).where(ChallengeFormat.is_default)
    )
    row.is_default = True
    await db.commit()
    await db.refresh(row)
    return row


async def delete(db: AsyncSession, format_id: int) -> bool:
    """Remove a format. Challenges made with it are untouched.

    They carry `format_name` as text precisely so their history survives this.
    """
    row = await db.get(ChallengeFormat, format_id)
    if row is None:
        return False
    await db.delete(row)
    await db.commit()
    return True


# --- link checking -------------------------------------------------------


async def _check(client: httpx.AsyncClient, url: str) -> bool:
    """Whether a URL resolves. HEAD first, GET as a fallback.

    Plenty of sites reject HEAD with 405 while serving the page perfectly, so
    treating a failed HEAD as a dead link would throw away good resources.
    """
    try:
        response = await client.head(url, follow_redirects=True)
        if response.status_code < 400:
            return True
        if response.status_code in (403, 405, 501):
            response = await client.get(url, follow_redirects=True)
            return response.status_code < 400
        return False
    except httpx.HTTPError:
        return False


async def verify_links(resources: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """Drop resources whose URL does not resolve.

    Models invent plausible URLs, and a challenge full of 404s undermines
    confidence in everything else on the page. Checked concurrently and capped,
    because this runs inside generation and the user is waiting.

    Returns the surviving resources and the URLs that were dropped, so the
    dropping is reportable rather than silent.
    """
    if not resources:
        return [], []

    checked = resources[:MAX_LINK_CHECKS]
    async with httpx.AsyncClient(
        timeout=LINK_TIMEOUT_SECONDS, headers={"User-Agent": "stack-exchange-scout/1.0"}
    ) as client:
        results = await asyncio.gather(
            *(_check(client, str(item.get("url") or "")) for item in checked),
            return_exceptions=True,
        )

    kept: list[dict[str, Any]] = []
    dropped: list[str] = []
    for item, ok in zip(checked, results, strict=False):
        if ok is True:
            kept.append(item)
        else:
            dropped.append(str(item.get("url") or ""))
            logger.info("Dropped unreachable resource: %s", item.get("url"))
    return kept, dropped


async def verify_content_links(
    content: dict[str, Any], blocks: list[challenge_blocks.Block]
) -> list[str]:
    """Verify every URL-bearing block in place. Returns what was dropped."""
    dropped: list[str] = []
    for block in blocks:
        if not block.has_urls:
            continue
        value = content.get(block.key)
        if not isinstance(value, list):
            continue
        kept, gone = await verify_links(value)
        content[block.key] = kept
        dropped.extend(gone)
    return dropped
