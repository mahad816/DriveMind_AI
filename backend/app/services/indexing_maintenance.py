"""Database-wide cooperative writer barrier; NOT proof of remote quiescence."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Session-exclusive recovery lock versus transaction-shared managed writers.
# Database-wide because the exhaustive inventory also examines all SQL owners.
LOCK_KEY = 0x44524956454D494E


async def writer_available(db: AsyncSession, *, wait: bool = False) -> bool:
    with db.no_autoflush:
        if wait:
            # Do not poison a live attempt during a brief recovery preflight.
            await db.execute(text("SELECT pg_advisory_xact_lock_shared(:key)"), {"key": LOCK_KEY})
            return True
        return bool(
            await db.scalar(
                text("SELECT pg_try_advisory_xact_lock_shared(:key)"), {"key": LOCK_KEY}
            )
        )
