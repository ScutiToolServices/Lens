"""Model setup verifies downloaded weights before installing anything."""

from hashlib import sha256

import httpx
import pytest

from src.models import MODELS, ModelInstaller, ModelSpec


async def test_bad_download_never_replaces_existing_model(tmp_path, monkeypatch):
    target = tmp_path / "eng.traineddata"
    target.write_bytes(b"old-model")
    real_client = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=b"bad-model"))
    monkeypatch.setattr("src.models.httpx.AsyncClient", lambda **kwargs: real_client(transport=transport))
    with pytest.raises(ValueError, match="Checksum"):
        await ModelInstaller().install("fast", tmp_path)
    assert target.read_bytes() == b"old-model"
    assert not list(tmp_path.glob("*.part"))


async def test_valid_download_and_reuse(tmp_path, monkeypatch):
    content = b"verified-test-model"
    monkeypatch.setitem(MODELS, "fast", ModelSpec("tessdata_fast", sha256(content).hexdigest()))
    calls = []

    def serve(request):
        calls.append(request.url)
        return httpx.Response(200, content=content)

    real_client = httpx.AsyncClient
    monkeypatch.setattr("src.models.httpx.AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(serve)))
    installer = ModelInstaller()
    assert (await installer.install("fast", tmp_path)).read_bytes() == content
    await installer.install("fast", tmp_path)
    assert len(calls) == 1
