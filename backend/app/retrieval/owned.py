"""Join parallel request-owned retrieval, including exceptional exits."""

import asyncio
from collections.abc import Awaitable
from typing import TypeVar

T = TypeVar("T")


async def gather_owned(*operations: Awaitable[T]) -> list[T]:
    tasks = [asyncio.ensure_future(operation) for operation in operations]
    try:
        return list(await asyncio.gather(*tasks))
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
