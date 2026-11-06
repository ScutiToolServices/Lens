"""Explicit per-call model selection behind a small replaceable engine interface."""

from collections.abc import Mapping
import hashlib
import io
import math
import os
from pathlib import Path
import shlex
import shutil
import threading
from typing import Protocol

from PIL import Image, UnidentifiedImageError
import pytesseract

from src.config import Settings
from src.contract import Mode
from src.errors import Rejected, Unavailable


class OcrEngine(Protocol):
    def recognize(self, crop: Image.Image, mode: Mode, timeout: float) -> tuple[str, float | None]:
        """Thread-safe crop recognition, with an explicit deadline in seconds."""
        ...

    def fingerprint(self, mode: Mode) -> str:
        """Identify the model and implementation for cache separation."""
        ...

    def status(self) -> Mapping[str, bool]:
        """Report model availability without downloading or running OCR."""
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


def summarize_words(data: dict) -> tuple[str, float | None]:
    """Preserve line boundaries and average nonempty valid word confidence rows."""
    lines, words, scores = [], [], []
    previous = None
    for index, value in enumerate(data["text"]):
        word = value.strip()
        score = float(data["conf"][index])
        if data["level"][index] != 5 or not word or not math.isfinite(score) or not 0 <= score <= 100:
            continue
        line = tuple(data[key][index] for key in ("page_num", "block_num", "par_num", "line_num"))
        if previous is not None and previous != line:
            lines.append(" ".join(words))
            words = []
        words.append(word)
        scores.append(score)
        previous = line
    if words:
        lines.append(" ".join(words))
    return "\n".join(lines), sum(scores) / len(scores) if scores else None


class TesseractEngine:
    """One binary, two explicit English model directories; no per-request environment mutation."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.command = shutil.which(settings.tesseract_cmd)
        self._fingerprints: dict[Path, tuple[tuple[int, int], str]] = {}
        self._lock = threading.Lock()
        if self.command:
            # Fixed for this service process; model choice is entirely in the config argument.
            pytesseract.pytesseract.tesseract_cmd = self.command

    def fingerprint(self, mode: Mode) -> str:
        if not self.command:
            raise Unavailable("Tesseract is missing. Install the CPU binary and set TESSERACT_CMD or PATH.")
        path = self.settings.model_dir(mode) / "eng.traineddata"
        try:
            with self._lock:
                info = path.stat()
                stamp = (info.st_mtime_ns, info.st_size)
                cached = self._fingerprints.get(path)
                if cached is None or cached[0] != stamp:
                    with path.open("rb") as model:
                        digest = hashlib.file_digest(model, "sha256").hexdigest()
                    self._fingerprints[path] = stamp, digest
                else:
                    digest = cached[1]
        except OSError:
            raise Unavailable(f"The {mode} English model is missing. Run uv run python -m src.models.") from None
        return f"tesseract-tsv-v1|{pytesseract.__version__}|{mode}|{digest}"

    def status(self) -> dict[str, bool]:
        return {mode: bool(self.command and (self.settings.model_dir(mode) / "eng.traineddata").is_file())
                for mode in ("fast", "accurate")}

    def recognize(self, crop: Image.Image, mode: Mode, timeout: float) -> tuple[str, float | None]:
        self.fingerprint(mode)
        directory = str(self.settings.model_dir(mode).resolve())
        if '"' in directory or "\n" in directory or "\r" in directory:
            raise Unavailable("Invalid model directory configuration.")
        # pytesseract 0.3.13 preserves literal config quotes on Windows.
        # Fail explicitly for unsupported Windows config paths instead of selecting another model.
        if os.name == "nt":
            if any(character.isspace() for character in directory):
                raise Unavailable("On Windows, configure OCR model directories without spaces.")
            argument = directory
        else:
            argument = shlex.quote(directory)
        try:
            data = pytesseract.image_to_data(
                crop, lang="eng", config=f"--oem 1 --tessdata-dir {argument}",
                output_type=pytesseract.Output.DICT, timeout=max(0.01, timeout),
            )
            return summarize_words(data)
        except (OSError, RuntimeError, ValueError):
            raise Unavailable("OCR failed or exceeded its time limit. Try a smaller image or fewer regions.") from None
