"""Owned image extraction, cache, global capacity and bounded region event streaming."""

import asyncio
from contextlib import aclosing, asynccontextmanager
import hashlib
import json
import time

from PIL import ImageOps

from src.config import Settings
from src.contract import ExtractRequest, ExtractResult, RegionResult, UploadResult
from src.engine import OcrEngine, decode_image
from src.errors import Busy, IdentityRequired, OCRError, Rejected, TooLarge, Unavailable
from src.options import snapshot
from src.store import Store
from src.work import cancel_and_drain, in_thread


class OCRService:
    """One process owns global CPU slots; async generators expose real completed regions."""

    def __init__(self, settings: Settings, engine: OcrEngine, store: Store, config=None):
        self.settings, self.engine, self.store, self.config = settings, engine, store, config
        self._start_lock = asyncio.Lock()
        self._started = False
        self._active = 0
        self._locks = {}

    async def start(self):
        async with self._start_lock:
            if not self._started:
                initial = await snapshot(self.settings, self.config)
                self._slots = asyncio.Semaphore(initial.concurrency)
                self._worker_count = initial.concurrency
                self._max_jobs = initial.max_jobs
                await in_thread(self.store.initialize)
                await in_thread(self.store.sweep)
                self._started = True

    @staticmethod
    def owner(owner: str) -> str:
        if not isinstance(owner, str) or not owner.strip() or len(owner) > 200:
            raise IdentityRequired("Send a requester username (1–200 characters).")
        return owner.strip()

    @asynccontextmanager
    async def _admission(self):
        # No await between testing and reserving capacity: event-loop-local accounting.
        if self._active >= self._max_jobs:
            raise Busy("OCR is busy. Try again shortly.")
        self._active += 1
        try:
            yield
        finally:
            self._active -= 1

    @asynccontextmanager
    async def _key_lock(self, key, deadline):
        lock, users = self._locks.get(key, (asyncio.Lock(), 0))
        self._locks[key] = lock, users + 1
        acquired = False
        try:
            await asyncio.wait_for(lock.acquire(), self._remaining(deadline))
            acquired = True
            yield
        finally:
            if acquired:
                lock.release()
            _, users = self._locks[key]
            if users == 1:
                del self._locks[key]
            else:
                self._locks[key] = lock, users - 1

    @staticmethod
    def _remaining(deadline):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError
        return remaining

    async def upload(self, owner: str, filename: str, data: bytes) -> UploadResult:
        owner = self.owner(owner)
        await self.start()
        settings = await snapshot(self.settings, self.config)
        if len(data) > settings.max_bytes:
            raise TooLarge("Image exceeds the upload byte limit.")
        async with self._admission():
            image = await in_thread(decode_image, data, settings.max_pixels)
            try:
                width, height = image.size
            finally:
                image.close()
            row = await in_thread(self.store.put, owner, filename, data, width, height,
                                  settings.ttl_seconds, settings.quota_bytes)
        return UploadResult(**row, message="Image uploaded. Choose fast or accurate for extraction; default is accurate.")

    async def extract(self, owner: str, request: ExtractRequest) -> ExtractResult:
        async with aclosing(self.stream(owner, request)) as events:
            async for event in events:
                if event["type"] == "complete":
                    return ExtractResult.model_validate(event["result"])
        raise Unavailable("OCR did not produce a complete result.")

    async def stream(self, owner: str, request: ExtractRequest):
        """Yield start, completed regions, then complete. Errors propagate to each transport."""
        owner = self.owner(owner)
        await self.start()
        settings = await snapshot(self.settings, self.config)
        deadline = time.monotonic() + settings.timeout_s
        try:
            async with self._admission():
                metadata = await in_thread(self.store.get, owner, request.file_id)
                if metadata["width"] * metadata["height"] > settings.max_pixels:
                    raise Rejected("Image exceeds the current decoded pixel limit.")
                boxes = request.regions or [(0, 0, metadata["width"], metadata["height"])]
                if len(boxes) > settings.max_regions:
                    raise Rejected("Too many regions for one image.")
                for x0, y0, x1, y1 in boxes:
                    if not (0 <= x0 < x1 <= metadata["width"] and 0 <= y0 < y1 <= metadata["height"]):
                        raise Rejected("Invalid region: require 0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height.")
                fingerprint = await in_thread(self.engine.fingerprint, request.mode)
                signature = hashlib.sha256(json.dumps(
                    [fingerprint, request.mode, boxes, request.preprocess], separators=(",", ":")
                ).encode()).hexdigest()
                async with self._key_lock((owner, request.file_id, signature), deadline):
                    payload = await in_thread(self.store.get_result, owner, request.file_id, signature)
                    cached = payload is not None
                    yield {"type": "start", "mode": request.mode, "total": len(boxes), "cached": cached}
                    rows = []
                    if cached:
                        result = ExtractResult.model_validate(payload)
                        if len(result.text) > settings.max_result_chars:
                            raise Rejected("OCR output exceeds the current character limit.")
                        for row in result.regions:
                            yield {"type": "region", "result": row.model_dump(mode="json")}
                    else:
                        content = await in_thread(self.store.get, owner, request.file_id, content=True)
                        async with aclosing(self._regions(content, boxes, request, settings, deadline)) as regions:
                            total_chars = 0
                            async for row in regions:
                                total_chars += len(row.text) + 1
                                if total_chars > settings.max_result_chars:
                                    raise Rejected("OCR output exceeds the character limit. Use smaller regions.")
                                rows.append(row)
                                yield {"type": "region", "result": row.model_dump(mode="json")}
                        rows.sort(key=lambda row: row.index)
                        result = ExtractResult(
                            file_id=request.file_id, mode=request.mode,
                            model="tessdata_best/eng" if request.mode == "accurate" else "tessdata_fast/eng",
                            regions=rows, text="\n".join(row.text for row in rows), cached=False,
                            message=f"Extracted {len(rows)} region(s) using {request.mode} CPU OCR.",
                        )
                        self._remaining(deadline)
                        await in_thread(self.store.put_result, owner, request.file_id, signature,
                                        result.model_dump(mode="json"), settings.quota_bytes)
                    result = result.model_copy(update={"cached": cached})
                    yield {"type": "complete", "result": result.model_dump(mode="json")}
        except TimeoutError:
            raise Unavailable("OCR job exceeded its time limit. Try fewer regions or fast mode.") from None

    async def _regions(self, data, boxes, request, settings, deadline):
        source = await in_thread(decode_image, data, settings.max_pixels)
        pending = iter(enumerate(boxes))
        queue = asyncio.Queue(maxsize=self._worker_count)

        def recognize(index, box):
            with source.crop(box) as crop:
                if request.preprocess:
                    with ImageOps.grayscale(crop) as gray, ImageOps.autocontrast(gray) as prepared:
                        text, confidence = self.engine.recognize(prepared, request.mode, self._remaining(deadline))
                else:
                    text, confidence = self.engine.recognize(crop, request.mode, self._remaining(deadline))
            return RegionResult(index=index, region=box, text=text, confidence=confidence)

        async def worker():
            try:
                for index, box in pending:
                    async with asyncio.timeout(self._remaining(deadline)):
                        async with self._slots:
                            result = await in_thread(recognize, index, box)
                    await queue.put(result)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                await queue.put(error)

        tasks = [asyncio.create_task(worker()) for _ in range(min(len(boxes), self._worker_count))]
        try:
            for _ in boxes:
                result = await asyncio.wait_for(queue.get(), self._remaining(deadline))
                if isinstance(result, Exception):
                    if isinstance(result, (OCRError, TimeoutError)):
                        raise result
                    raise Unavailable("OCR failed. Try another image.") from None
                yield result
        finally:
            await cancel_and_drain(tasks)
            source.close()
