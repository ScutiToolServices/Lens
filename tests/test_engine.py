"""The remote engine talks to a OCR_Tesseract_Model service through the saved "ocr" slot; no real Tesseract is needed."""

import json

import httpx
from PIL import Image
import pytest

from src.admin_api import Backends, ProbeError
from src.engine import RemoteOcrEngine, decode_image, probe_modes
from src.errors import Busy, Rejected, Unavailable
from tests.test_core import image_bytes

MODES = {"fast": {"available": True, "fingerprint": "tesseract-tsv-v1|fast|aaa"},
         "accurate": {"available": True, "fingerprint": "tesseract-tsv-v1|accurate|bbb"}}


def engine_for(tmp_path, handler, url="http://ocr:29261", token="tok"):
    backends = Backends(tmp_path / "backends.json")
    if url:
        backends.set("ocr", url, token)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return RemoteOcrEngine(backends, client=client)


def service(seen=None, modes=MODES, ocr=None):
    def handler(request):
        if seen is not None:
            seen.append(request)
        if request.url.path == "/v1/modes":
            return httpx.Response(200, json={"modes": modes, "default": "accurate"})
        return ocr(request) if ocr else httpx.Response(200, json={"text": "Hello\nworld", "confidence": 90})
    return handler


def test_decode_accepts_one_static_image_within_the_pixel_limit():
    assert decode_image(image_bytes(), 10_000_000).size[0] > 0
    with pytest.raises(Rejected):
        decode_image(image_bytes(), 1)
    with pytest.raises(Rejected):
        decode_image(b"not an image", 100)


def test_recognize_sends_the_crop_as_png_with_mode_timeout_and_token(tmp_path):
    seen = []
    engine = engine_for(tmp_path, service(seen))
    text, confidence = engine.recognize(Image.new("RGB", (12, 6), "white"), "fast", 7)
    assert (text, confidence) == ("Hello\nworld", 90.0)
    call = seen[-1]
    assert call.url.path == "/v1/ocr" and call.url.params["mode"] == "fast" and float(call.url.params["timeout"]) == 7
    assert call.headers["x-internal-token"] == "tok" and call.content.startswith(b"\x89PNG")
    assert Image.open(__import__("io").BytesIO(call.content)).size == (12, 6)


def test_the_fingerprint_comes_from_the_service_and_is_reused_briefly(tmp_path):
    seen = []
    engine = engine_for(tmp_path, service(seen))
    assert engine.fingerprint("fast") == "remote|tesseract-tsv-v1|fast|aaa"
    assert engine.fingerprint("accurate") == "remote|tesseract-tsv-v1|accurate|bbb"
    assert len([r for r in seen if r.url.path == "/v1/modes"]) == 1


def test_a_missing_mode_is_unavailable_and_status_says_which(tmp_path):
    engine = engine_for(tmp_path, service(modes={"fast": MODES["fast"], "accurate": {"available": False, "fingerprint": None}}))
    assert engine.status() == {"fast": True, "accurate": False}
    with pytest.raises(Unavailable, match="no model"):
        engine.fingerprint("accurate")


def test_no_saved_connection_is_unavailable_with_a_hint_and_no_call(tmp_path):
    engine = engine_for(tmp_path, lambda request: pytest.fail("No request expected"), url="")
    assert engine.status() == {"fast": False, "accurate": False}
    with pytest.raises(Unavailable, match="admin page"):
        engine.recognize(Image.new("RGB", (4, 4)), "fast", 5)


@pytest.mark.parametrize("code,error,words", [(429, Busy, "busy"), (401, Unavailable, "token"), (503, Unavailable, "model files"), (500, Unavailable, "OCR failed")])
def test_refusals_become_safe_messages(tmp_path, code, error, words):
    engine = engine_for(tmp_path, service(ocr=lambda request: httpx.Response(code, text="secret /srv/path http://private")))
    with pytest.raises(error, match=words) as caught:
        engine.recognize(Image.new("RGB", (4, 4)), "fast", 5)
    assert "secret" not in str(caught.value) and "ocr:29261" not in str(caught.value)


def test_connection_errors_and_odd_answers_are_safe(tmp_path):
    def broken(request):
        raise httpx.ConnectError("http://private")
    with pytest.raises(Unavailable, match="could not be reached") as caught:
        engine_for(tmp_path, broken).recognize(Image.new("RGB", (4, 4)), "fast", 5)
    assert "private" not in str(caught.value)
    odd = service(ocr=lambda request: httpx.Response(200, json={"text": 5, "confidence": "x"}))
    with pytest.raises(Unavailable, match="unexpected"):
        engine_for(tmp_path, odd).recognize(Image.new("RGB", (4, 4)), "fast", 5)


def test_a_saved_connection_change_applies_to_the_next_call(tmp_path):
    seen = []
    engine = engine_for(tmp_path, service(seen))
    engine.recognize(Image.new("RGB", (4, 4)), "fast", 5)
    engine.backends.set("ocr", "http://other:29261", "t2")
    engine.recognize(Image.new("RGB", (4, 4)), "fast", 5)
    assert [r.url.host for r in seen if r.url.path == "/v1/ocr"] == ["ocr", "other"]


async def test_probe_reports_the_ready_modes(monkeypatch):
    real = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"modes": MODES}))
    monkeypatch.setattr("src.admin_api.httpx.AsyncClient", lambda **kwargs: real(transport=transport))
    assert "accurate, fast" in await probe_modes("http://ocr:29261", "tok")
    bad = httpx.MockTransport(lambda request: httpx.Response(200, json={"nope": 1}))
    monkeypatch.setattr("src.admin_api.httpx.AsyncClient", lambda **kwargs: real(transport=bad))
    with pytest.raises(ProbeError, match="OCR_Tesseract_Model"):
        await probe_modes("http://ocr:29261", "tok")
