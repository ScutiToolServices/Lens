"""Word scores, explicit model routing and a real CPU OCR round trip."""

import asyncio
from dataclasses import replace
import os
import shutil

from PIL import Image, ImageDraw, ImageFont
import pytest

from src.config import Settings
from src.engine import TesseractEngine, summarize_words
from src.errors import Unavailable
from src.models import MODELS, file_digest
from src.work import in_thread


def words():
    return {"level": [4, 5, 5, 5, 5], "text": ["", "HELLO", "world", "", "bad"],
            "conf": [-1, 80, 100, 50, -1], "page_num": [1] * 5,
            "block_num": [1] * 5, "par_num": [1] * 5, "line_num": [1, 1, 2, 2, 2]}


def test_word_confidence_ignores_empty_negative_and_nonfinite_rows():
    data = words()
    assert summarize_words(data) == ("HELLO\nworld", 90.0)
    data["conf"][1] = float("nan")
    assert summarize_words(data) == ("world", 100.0)
    data["text"] = [""] * 5
    assert summarize_words(data) == ("", None)


async def test_concurrent_engine_calls_use_explicit_models_not_environment(tmp_path, monkeypatch):
    for mode in ("fast", "accurate"):
        (tmp_path / "models" / mode).mkdir(parents=True)
        (tmp_path / "models" / mode / "eng.traineddata").write_bytes(mode.encode())
    monkeypatch.setattr("src.engine.shutil.which", lambda command: "tesseract")
    seen = []
    original_prefix = os.environ.get("TESSDATA_PREFIX")

    def recognize(image, **kwargs):
        seen.append(kwargs["config"])
        return words()

    monkeypatch.setattr("src.engine.pytesseract.image_to_data", recognize)
    engine = TesseractEngine(Settings(data_dir=tmp_path))
    with Image.new("RGB", (20, 20)) as image:
        await asyncio.gather(*(in_thread(engine.recognize, image, mode, 10) for mode in ("fast", "accurate")))
    assert any(str(tmp_path / "models" / "fast") in config for config in seen)
    assert any(str(tmp_path / "models" / "accurate") in config for config in seen)
    assert all("--oem 1" in config for config in seen)
    assert os.environ.get("TESSDATA_PREFIX") == original_prefix
    assert engine.fingerprint("fast") != engine.fingerprint("accurate")


def test_missing_binary_or_model_returns_install_hint_without_path(tmp_path, monkeypatch):
    monkeypatch.setattr("src.engine.shutil.which", lambda command: None)
    engine = TesseractEngine(Settings(data_dir=tmp_path))
    with pytest.raises(Unavailable, match="TESSERACT_CMD"):
        engine.fingerprint("accurate")
    assert engine.status() == {"fast": False, "accurate": False}


@pytest.mark.parametrize("mode", ["fast", "accurate"])
async def test_real_cpu_round_trip(mode):
    settings = Settings()
    command = os.environ.get("TESSERACT_CMD") or shutil.which("tesseract")
    if not command or not settings.model_dir(mode).joinpath("eng.traineddata").is_file():
        pytest.skip("Install Tesseract and run uv run python -m src.models for real CPU OCR tests.")
    settings = replace(settings, tesseract_cmd=command)
    assert await in_thread(file_digest, settings.model_dir(mode) / "eng.traineddata") == MODELS[mode].sha256
    image = Image.new("RGB", (600, 120), "white")
    ImageDraw.Draw(image).text((20, 20), "HELLO 123", fill="black", font=ImageFont.load_default(size=48))
    try:
        text, confidence = await in_thread(TesseractEngine(settings).recognize, image, mode, 10)
        assert text.strip() == "HELLO 123"
        assert 0 <= confidence <= 100
    finally:
        image.close()
