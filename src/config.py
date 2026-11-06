"""Environment-only configuration; credentials are never read from project files."""

from dataclasses import dataclass
import os
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 8093
    internal_token: str = ""
    admin_password: str = ""
    data_dir: Path = PROJECT_DIR / ".data"
    tesseract_cmd: str = "tesseract"
    fast_dir: Path | None = None
    accurate_dir: Path | None = None
    max_bytes: int = 10 * 1024 * 1024
    max_pixels: int = 16_000_000
    max_regions: int = 32
    max_result_chars: int = 250_000
    timeout_s: float = 110.0
    ttl_seconds: int = 86400
    quota_bytes: int = 200 * 1024 * 1024
    concurrency: int = 2
    max_jobs: int = 4

    def __post_init__(self):
        for name in ("max_bytes", "max_pixels", "max_regions", "max_result_chars", "timeout_s",
                     "ttl_seconds", "quota_bytes", "concurrency", "max_jobs"):
            if getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive")
        if not 1 <= self.port <= 65535:
            raise ValueError("port must be between 1 and 65535")
        if self.max_regions > 256:
            raise ValueError("max_regions cannot exceed 256")

    @property
    def exposed_without_token(self):
        return self.host not in {"localhost", "127.0.0.1", "::1"} and not self.internal_token

    def model_dir(self, mode: str) -> Path:
        override = self.fast_dir if mode == "fast" else self.accurate_dir
        return override or self.data_dir / "models" / mode


def load_settings() -> Settings:
    env = os.environ.get
    return Settings(
        host=env("LENS_HOST", "127.0.0.1"), port=int(env("LENS_PORT", "8093")),
        internal_token=env("INTERNAL_API_TOKEN", ""), admin_password=env("LENS_ADMIN_PASSWORD", ""),
        data_dir=Path(env("LENS_DATA_DIR", str(PROJECT_DIR / ".data"))),
        tesseract_cmd=env("TESSERACT_CMD", "tesseract"),
        fast_dir=Path(env("LENS_FAST_TESSDATA_DIR")) if env("LENS_FAST_TESSDATA_DIR") else None,
        accurate_dir=Path(env("LENS_ACCURATE_TESSDATA_DIR")) if env("LENS_ACCURATE_TESSDATA_DIR") else None,
        max_bytes=int(float(env("LENS_MAX_UPLOAD_MB", "10")) * 1024 * 1024),
        max_pixels=int(env("LENS_MAX_PIXELS", "16000000")), max_regions=int(env("LENS_MAX_REGIONS", "32")),
        max_result_chars=int(env("LENS_MAX_RESULT_CHARS", "250000")), timeout_s=float(env("LENS_TIMEOUT_S", "110")),
        ttl_seconds=int(env("LENS_TTL_HOURS", "24")) * 3600,
        quota_bytes=int(env("LENS_QUOTA_MB", "200")) * 1024 * 1024,
        concurrency=int(env("LENS_CONCURRENCY", "2")), max_jobs=int(env("LENS_MAX_JOBS", "4")),
    )
