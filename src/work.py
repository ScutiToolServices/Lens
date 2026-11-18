"""Cancellation-safe adapter for bounded blocking work."""

import asyncio

import anyio


async def drain(task):
    """Resist ASGI level cancellation and repeated direct cancels until work ends."""
    with anyio.CancelScope(shield=True):
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        # Retrieve exceptions to avoid unhandled-task warnings during cleanup.
        if not task.cancelled():
            task.exception()


async def cancel_and_drain(tasks):
    """Cancel coroutine workers without abandoning blocking work they already own."""
    with anyio.CancelScope(shield=True):
        for task in tasks:
            if not task.done():
                task.cancel()
        for task in tasks:
            await drain(task)


async def in_thread(function, *args, **kwargs):
    """Keep ownership of resources until an already-started thread actually ends."""
    task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await drain(task)
        raise
