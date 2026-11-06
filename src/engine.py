"""OCR behind a small replaceable engine interface: crops go to a TesseractModel service chosen on the admin page."""

from collections.abc import Mapping
import io
import threading
import time
from typing import Protocol

import httpx
from PIL import Image, UnidentifiedImageError

from src.contract import Mode
from src.errors import Busy, Rejected, Unavailable

MODES_KEPT_SECONDS = 5.0  # how long one answer of the service's /v1/modes is reused


class OcrEngine(Protocol):
    def recognize(self, crop: Image.Image, mode: Mode, timeout: float) -> tuple[str, float | None]:
        """Thread-safe crop recognition, with an explicit deadline in seconds."""
        ...

    def fingerprint(self, mode: Mode) -> str:
        """Identify the model and implementation for cache separation."""
        ...

    def status(self) -> Mapping[str, bool]:
        """Report model availability without running OCR."""
        ...


def decode_image(data: bytes, max_pixels: int) -> Image.Image:
    """Decode one supported static image, checking dimensions before allocating pixels."""
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in {"PNG", "JPEG", "WEBP"} or getattr(image, "n_frames", 1) != 1:
                raise Rejected("Send a static PNG, JPEG or WebP image.")
            if image.width * image.height > max_pixels:
                raise Rejected("Image exceeds the decoded pixel limit.")
            image.load()
            return image.copy()
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise Rejected("Image cannot be decoded. Send a valid PNG, JPEG or WebP.") from None


def failure(code: int) -> Unavailable:
    """One safe message per refusal: no address, no text from the model service."""
    if code == 429:
        return Busy("The OCR model service is busy. Try again shortly.")
    if code in (401, 403):
        return Unavailable("The OCR model service refused this service's token. Check the saved connection.")
    if code == 503:
        return Unavailable("The OCR model service has no model for this mode yet. Install its model files.")
    return Unavailable("OCR failed or exceeded its time limit. Try a smaller image or fewer regions.")


class RemoteOcrEngine:
    """The "ocr" slot of `backends` (address and token saved on the admin page, read on every call). Calls are
    blocking on purpose: the service runs every crop in a worker thread."""

    def __init__(self, backends, slot: str = "ocr", client: httpx.Client | None = None) -> None:
        self.backends, self.slot, self._client = backends, slot, client
        self._lock = threading.Lock()
        self._seen: tuple[str, float, dict] | None = None  # (address, when, the modes answer)

    def _location(self) -> tuple[str, dict[str, str]]:
        found = self.backends.get(self.slot)
        if found is None:
            raise Unavailable("No OCR model service is set. Save a connection on the Lens admin page.")
        url, token = found
        return url, {"X-Internal-Token": token} if token else {}

    def _call(self, method: str, path: str, timeout: float, **kwargs) -> httpx.Response:
        url, headers = self._location()
        client = self._client or httpx.Client(follow_redirects=False)
        try:
            return client.request(method, url + path, headers=headers,
                                  timeout=httpx.Timeout(timeout, connect=min(5.0, timeout)), **kwargs)
        except (httpx.HTTPError, ValueError):
            raise Unavailable("The OCR model service could not be reached or timed out.") from None
        finally:
            if self._client is None:
                client.close()

    def _modes(self) -> dict:
        url = self._location()[0]
        with self._lock:
            if self._seen and self._seen[0] == url and time.monotonic() - self._seen[1] < MODES_KEPT_SECONDS:
                return self._seen[2]
        reply = self._call("GET", "/v1/modes", 10.0)
        if reply.status_code != 200:
            raise failure(reply.status_code)
        try:
            modes = reply.json()["modes"]
            if not isinstance(modes, dict):
                raise ValueError
        except (ValueError, KeyError, TypeError):
            raise Unavailable("The OCR model service gave an unexpected answer.") from None
        with self._lock:
            self._seen = (url, time.monotonic(), modes)
        return modes

    def fingerprint(self, mode: Mode) -> str:
        row = self._modes().get(mode) or {}
        if not row.get("available") or not isinstance(row.get("fingerprint"), str):
            raise Unavailable("The OCR model service has no model for this mode yet. Install its model files.")
        return "remote|" + row["fingerprint"]

    def status(self) -> dict[str, bool]:
        try:
            modes = self._modes()
        except Unavailable:
            return {"fast": False, "accurate": False}
        return {mode: bool((modes.get(mode) or {}).get("available")) for mode in ("fast", "accurate")}

    def recognize(self, crop: Image.Image, mode: Mode, timeout: float) -> tuple[str, float | None]:
        stream = io.BytesIO()
        crop.save(stream, "PNG")
        wait = max(0.1, timeout)
        reply = self._call("POST", "/v1/ocr", wait + 5, params={"mode": mode, "timeout": f"{wait:.2f}"},
                           content=stream.getvalue())
        if reply.status_code != 200:
            raise failure(reply.status_code)
        try:
            body = reply.json()
            text, confidence = body["text"], body["confidence"]
            if not isinstance(text, str) or not (confidence is None or isinstance(confidence, (int, float))):
                raise ValueError
        except (ValueError, KeyError, TypeError):
            raise Unavailable("The OCR model service gave an unexpected answer.") from None
        return text, None if confidence is None else float(confidence)


async def probe_modes(url: str, token: str) -> str:
    """Connection test for the admin page: which modes the service can answer."""
    from src.admin_api import ProbeError, check

    reply = await check(url, token, "/v1/modes")
    try:
        modes = reply.json()["modes"]
        ready = sorted(mode for mode, row in modes.items() if row.get("available"))
    except (ValueError, KeyError, TypeError, AttributeError):
        raise ProbeError("That address does not look like a TesseractModel service.") from None
    return "Reachable; ready modes: " + (", ".join(ready) if ready else "none (install the model files)") + "."
