"""Explicit, checksum-verified installation of official English CPU OCR weights."""

import argparse
import asyncio
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import uuid

import httpx

from src.config import load_settings
from src.work import in_thread


@dataclass(frozen=True)
class ModelSpec:
    repository: str
    sha256: str


MODELS = {
    "fast": ModelSpec("tessdata_fast", "7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2"),
    "accurate": ModelSpec("tessdata_best", "8280aed0782fe27257a68ea10fe7ef324ca0f8d85bd2fd145d1c2b560bcb66ba"),
}


def file_digest(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


class ModelInstaller:
    """Install only known official weights; OCR requests never call this class."""

    async def install(self, mode: str, directory: Path) -> Path:
        spec = MODELS[mode]
        destination = directory / "eng.traineddata"
        await in_thread(directory.mkdir, parents=True, exist_ok=True)
        if await in_thread(destination.is_file):
            if await in_thread(file_digest, destination) == spec.sha256:
                return destination
        temporary = directory / f"eng.{uuid.uuid4().hex}.part"
        source = await in_thread(temporary.open, "xb")
        try:
            url = f"https://raw.githubusercontent.com/tesseract-ocr/{spec.repository}/main/eng.traineddata"
            digest, size = hashlib.sha256(), 0
            async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
                async with client.stream("GET", url) as response:
                    response.raise_for_status()
                    async for chunk in response.aiter_bytes(256 * 1024):
                        size += len(chunk)
                        if size > 32 * 1024 * 1024:
                            raise ValueError("Downloaded model exceeds its expected size bound.")
                        digest.update(chunk)
                        await in_thread(source.write, chunk)
            if digest.hexdigest() != spec.sha256:
                raise ValueError(f"Checksum verification failed for {mode}; installed model was not replaced.")
            await in_thread(source.close)
            await in_thread(os.replace, temporary, destination)
            return destination
        finally:
            await in_thread(source.close)
            await in_thread(temporary.unlink, missing_ok=True)


async def run(mode: str):
    settings = load_settings()
    installer = ModelInstaller()
    for selected in MODELS if mode == "all" else [mode]:
        path = await installer.install(selected, settings.model_dir(selected))
        print(f"{selected}: verified English model ready at {path}")


def main():
    parser = argparse.ArgumentParser(description="Download official English fast/best models; no binary installation.")
    parser.add_argument("--mode", choices=["all", "fast", "accurate"], default="all")
    args = parser.parse_args()
    try:
        asyncio.run(run(args.mode))
    except (OSError, ValueError, httpx.HTTPError) as error:
        parser.exit(1, f"Model setup failed: {error}\n")


if __name__ == "__main__":
    main()
