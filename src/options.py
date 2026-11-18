"""Service-specific live settings on the unchanged peer admin runtime."""

from dataclasses import replace

from src.config import Settings
from src.runtime import Config, Setting
from src.work import in_thread


def make_config(settings: Settings) -> Config | None:
    if not settings.admin_password:
        return None
    limits = [
        ("max_bytes", "Largest upload (bytes)", 1, 100 * 1024 * 1024, False),
        ("max_pixels", "Most decoded pixels", 1, 50_000_000, False),
        ("max_regions", "Most regions per image", 1, 256, False),
        ("max_result_chars", "Most output characters", 1, 1_000_000, False),
        ("ttl_seconds", "Keep uploads (seconds)", 60, 31_536_000, False),
        ("quota_bytes", "Storage per requester (bytes)", 1, 10 * 1024**3, False),
        ("concurrency", "Global OCR workers", 1, 16, True),
        ("max_jobs", "Admitted extraction jobs", 1, 32, True),
    ]
    schema = [Setting(key, label, "int", getattr(settings, key), minimum=low, maximum=high, restart=restart)
              for key, label, low, high, restart in limits]
    schema.append(Setting("timeout_s", "Job time limit (seconds)", "float", settings.timeout_s,
                          minimum=0.1, maximum=110,
                          help="Includes queued OCR work. Keep below Citadel's 120-second tool timeout."))
    schema.append(Setting("data_path", "Data folder", "text", "", restart=True,
                          help=f"Where the result cache and uploads go. Empty = {settings.state_dir}. Applies after a restart; "
                               "files already stored are not moved. Settings and the saved model connection stay in the standard folder."))
    return Config(settings.state_dir / "settings.json", schema)


async def snapshot(base: Settings, config: Config | None) -> Settings:
    """Resolve file-backed options in a worker instead of on the event loop."""
    if config is None:
        return base

    def resolve():
        return replace(base, **{row["key"]: row["value"] for row in config.describe() if row["key"] != "data_path"})

    return await in_thread(resolve)
