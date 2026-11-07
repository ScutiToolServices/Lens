"""Environment-only configuration; credentials are never read from project files."""

from dataclasses import dataclass, replace
import json
import logging
import os
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    host: str = "127.0.0.1"
    port: int = 29403
    internal_token: str = ""
    admin_password: str = ""
    data_dir: Path = PROJECT_DIR / ".data"
    config_dir: Path | None = None  # set when the data folder was moved: the folder that keeps settings.json
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
    def state_dir(self) -> Path:
        """Where settings.json and backends.json live: the first data folder, even after the data folder was moved."""
        return self.config_dir or self.data_dir

    @property
    def exposed_without_token(self):
        return self.host not in {"localhost", "127.0.0.1", "::1"} and not self.internal_token


def _from_environment() -> Settings:
    env = os.environ.get
    return Settings(
        host=env("SERVICE_HOST", "127.0.0.1"), port=int(env("SERVICE_PORT", "29403")),
        internal_token=env("INTERNAL_API_TOKEN", ""), admin_password=env("SERVICE_ADMIN_PASSWORD", ""),
        data_dir=Path(env("SERVICE_DATA_DIR", str(PROJECT_DIR / ".data"))),
        max_bytes=int(float(env("SERVICE_MAX_UPLOAD_MB", "10")) * 1024 * 1024),
        max_pixels=int(env("SERVICE_MAX_PIXELS", "16000000")), max_regions=int(env("SERVICE_MAX_REGIONS", "32")),
        max_result_chars=int(env("SERVICE_MAX_RESULT_CHARS", "250000")), timeout_s=float(env("SERVICE_TIMEOUT_S", "110")),
        ttl_seconds=int(env("SERVICE_TTL_HOURS", "24")) * 3600,
        quota_bytes=int(env("SERVICE_QUOTA_MB", "200")) * 1024 * 1024,
        concurrency=int(env("SERVICE_CONCURRENCY", "2")), max_jobs=int(env("SERVICE_MAX_JOBS", "4")),
    )


def with_saved_data_path(settings: Settings) -> Settings:
    """The admin page's "Data folder" setting moves stored data (audio, uploads, voices, results) to another folder.
    It is read once, here at start. Settings and saved model connections stay in the first folder, which is where this
    value is saved. A folder that cannot be written is ignored."""
    try:
        saved = json.loads((settings.data_dir / "settings.json").read_text("utf-8")).get("data_path")
    except (OSError, ValueError, AttributeError):
        return settings
    if not isinstance(saved, str) or not saved.strip():
        return settings
    target = Path(saved.strip()).expanduser()
    if not target.is_absolute():
        target = PROJECT_DIR / target
    try:
        target.mkdir(parents=True, exist_ok=True)
        probe = target / ".write-test"
        probe.write_text("x")
        probe.unlink()
    except OSError:
        logging.getLogger(__name__).warning("Data folder %s cannot be written; using %s", target, settings.data_dir)
        return settings
    return replace(settings, data_dir=target, config_dir=settings.data_dir)


def load_settings() -> Settings:
    return with_saved_data_path(_from_environment())
