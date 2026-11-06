"""Test the service contract and safety bounds without requiring installed models."""

import asyncio
from dataclasses import replace
import io
import threading
import time

import anyio
from PIL import Image
from PIL.PngImagePlugin import PngInfo
import pytest
from pydantic import ValidationError

from src.config import Settings
from src.contract import ExtractRequest
from src.errors import Busy, Rejected, Unavailable, Missing, QuotaExceeded
from src.service import OCRService
from src.store import Store


def image_bytes():
    image = Image.new("RGB", (40, 20), "red")
    image.paste("blue", (20, 0, 40, 20))
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


class FakeEngine:
    def __init__(self, delay=0.01):
        self.delay = delay
        self.calls = []
        self.active = 0
        self.peak = 0
        self.lock = threading.Lock()
        self.main_thread = threading.get_ident()

    def fingerprint(self, mode):
        return "test-" + mode

    def status(self):
        return {"fast": True, "accurate": True}

    def recognize(self, crop, mode, timeout):
        assert threading.get_ident() != self.main_thread
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            time.sleep(self.delay)
            self.calls.append((mode, crop.size, crop.mode, crop.getpixel((0, 0))))
            return f"{mode}: {crop.getpixel((0, 0))}", 90.0
        finally:
            with self.lock:
                self.active -= 1


def make_service(tmp_path, engine=None, **kwargs):
    settings = replace(Settings(data_dir=tmp_path), **kwargs)
    return OCRService(settings, engine or FakeEngine(), Store(tmp_path / "ocr.sqlite3"))


async def upload(service, owner="ann"):
    return await service.upload(owner, "image.png", image_bytes())


def test_default_and_boundary_contract():
    assert ExtractRequest(file_id="a" * 32).mode == "accurate"
    for changes in ({"mode": "auto"}, {"regions": [[0, 0, 1.5, 2]]},
                    {"regions": [[0, 0, True, 2]]}, {"owner": "other"}, {"file_id": "../x"}):
        with pytest.raises(ValidationError):
            ExtractRequest.model_validate({"file_id": "a" * 32, **changes})


async def test_default_fast_crops_and_cache_separation(tmp_path):
    engine = FakeEngine()
    service = make_service(tmp_path, engine)
    file = await upload(service)
    request = ExtractRequest(file_id=file.file_id, regions=[(0, 0, 20, 20), (20, 0, 40, 20)])
    accurate = await service.extract("ann", request)
    assert accurate.mode == "accurate" and not accurate.cached
    assert [row.region for row in accurate.regions] == request.regions
    assert {call[3] for call in engine.calls} == {(255, 0, 0), (0, 0, 255)}
    assert [row.text for row in accurate.regions] == ["accurate: (255, 0, 0)", "accurate: (0, 0, 255)"]
    assert all(call[1] == (20, 20) for call in engine.calls)
    assert (await service.extract("ann", request)).cached
    fast = await service.extract("ann", request.model_copy(update={"mode": "fast"}))
    assert fast.mode == "fast" and not fast.cached
    assert (await service.extract("ann", request)).cached
    await service.extract("ann", request.model_copy(update={"preprocess": True}))
    assert engine.calls[-1][2] == "L"
    assert len(engine.calls) == 6


@pytest.mark.parametrize("box", [(-1, 0, 10, 10), (0, 0, 41, 10), (0, 0, 10, 21),
                                 (10, 0, 10, 10), (0, 10, 10, 5)])
async def test_outside_or_empty_box_rejected_before_engine(tmp_path, box):
    engine = FakeEngine()
    service = make_service(tmp_path, engine)
    file = await upload(service)
    with pytest.raises(Rejected):
        await service.extract("ann", ExtractRequest(file_id=file.file_id, regions=[box]))
    assert not engine.calls


async def test_ownership_and_upload_validation(tmp_path):
    service = make_service(tmp_path)
    file = await upload(service)
    with pytest.raises(Missing):
        await service.extract("bob", ExtractRequest(file_id=file.file_id))
    with pytest.raises(Rejected):
        await service.upload("ann", "bad.png", b"not an image")
    small = make_service(tmp_path / "small", max_pixels=100)
    with pytest.raises(Rejected):
        await upload(small)
    with pytest.raises(Rejected):
        await make_service(tmp_path / "bytes", max_bytes=10).upload("ann", "x", image_bytes())


async def test_quota_deduplicates_and_expiry_clears_results(tmp_path):
    service = make_service(tmp_path, quota_bytes=len(image_bytes()) + 2000)
    file = await upload(service)
    assert (await upload(service)).file_id == file.file_id
    await service.extract("ann", ExtractRequest(file_id=file.file_id))
    removed = await asyncio.to_thread(service.store.sweep, time.time() + 90000)
    assert removed == 1
    with pytest.raises(Missing):
        await service.extract("ann", ExtractRequest(file_id=file.file_id))
    with pytest.raises(QuotaExceeded):
        await upload(make_service(tmp_path / "quota", quota_bytes=10))


async def test_stream_reports_regions_then_complete(tmp_path):
    service = make_service(tmp_path)
    file = await upload(service)
    request = ExtractRequest(file_id=file.file_id, regions=[(0, 0, 20, 20), (20, 0, 40, 20)])
    events = [event async for event in service.stream("ann", request)]
    assert [event["type"] for event in events] == ["start", "region", "region", "complete"]
    assert sorted(event["result"]["index"] for event in events if event["type"] == "region") == [0, 1]
    assert events[-1]["result"]["mode"] == "accurate"
    cached = [event async for event in service.stream("ann", request)]
    assert cached[0]["cached"] is True and cached[-1]["result"]["cached"] is True


async def test_global_limits_span_mixed_modes_and_cancellation_drains_threads(tmp_path):
    engine = FakeEngine(delay=0.08)
    service = make_service(tmp_path, engine, concurrency=1)
    file = await upload(service)
    requests = [ExtractRequest(file_id=file.file_id, mode=mode) for mode in ("accurate", "fast")]
    results = await asyncio.gather(*(service.extract("ann", request) for request in requests))
    assert {result.mode for result in results} == {"fast", "accurate"}
    assert engine.peak == 1
    task = asyncio.create_task(service.extract("ann", requests[0].model_copy(update={"preprocess": True})))
    while not engine.active:
        await asyncio.sleep(0.001)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert engine.active == 0


async def test_failed_region_never_populates_cache(tmp_path):
    class FailingEngine(FakeEngine):
        def recognize(self, crop, mode, timeout):
            raise Unavailable("Recognition failed. Try again.")

    service = make_service(tmp_path, FailingEngine())
    file = await upload(service)
    request = ExtractRequest(file_id=file.file_id)
    with pytest.raises(Unavailable):
        await service.extract("ann", request)
    service.engine = FakeEngine()
    assert not (await service.extract("ann", request)).cached


async def test_anyio_disconnect_scope_keeps_slot_until_thread_finishes(tmp_path):
    engine = FakeEngine(delay=0.2)
    service = make_service(tmp_path, engine, concurrency=1)
    file = await upload(service)
    async with anyio.create_task_group() as group:
        group.start_soon(service.extract, "ann", ExtractRequest(file_id=file.file_id))
        while not engine.active:
            await asyncio.sleep(0.001)
        group.cancel_scope.cancel()
    assert engine.active == 0
    assert service._active == 0
    assert not service._locks


async def test_compressed_png_metadata_rejected_safely(tmp_path):
    metadata = PngInfo()
    metadata.add_text("Comment", "x" * (2 * 1024 * 1024), zip=True)
    buffer = io.BytesIO()
    Image.new("RGB", (1, 1)).save(buffer, "PNG", pnginfo=metadata)
    with pytest.raises(Rejected):
        await make_service(tmp_path).upload("ann", "metadata.png", buffer.getvalue())


async def test_timeout_drains_worker_and_duplicate_requests_share_cache(tmp_path):
    engine = FakeEngine(delay=0.08)
    service = make_service(tmp_path, engine, timeout_s=0.02, concurrency=1)
    file = await upload(service)
    with pytest.raises(Unavailable, match="time limit"):
        await service.extract("ann", ExtractRequest(file_id=file.file_id))
    assert engine.active == 0
    assert not service._locks
    normal = make_service(tmp_path / "normal", FakeEngine())
    file = await upload(normal)
    request = ExtractRequest(file_id=file.file_id)
    results = await asyncio.gather(normal.extract("ann", request), normal.extract("ann", request))
    assert sorted(result.cached for result in results) == [False, True]
    assert len(normal.engine.calls) == 1


async def test_capacity_rejects_excess_job_without_extra_ocr(tmp_path):
    engine = FakeEngine(delay=0.1)
    service = make_service(tmp_path, engine, max_jobs=1)
    file = await upload(service)
    request = ExtractRequest(file_id=file.file_id)
    first = asyncio.create_task(service.extract("ann", request))
    try:
        while not engine.active:
            await asyncio.sleep(0.001)
        with pytest.raises(Busy):
            await service.extract("ann", request.model_copy(update={"mode": "fast"}))
    finally:
        await first
    assert len(engine.calls) == 1


async def test_repeated_task_cancellation_does_not_release_live_worker(tmp_path):
    engine = FakeEngine(delay=0.15)
    service = make_service(tmp_path, engine, concurrency=1)
    file = await upload(service)
    task = asyncio.create_task(service.extract("ann", ExtractRequest(file_id=file.file_id)))
    while not engine.active:
        await asyncio.sleep(0.001)
    task.cancel()
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert engine.active == 0 and service._active == 0
