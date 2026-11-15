"""Load and validate config/settings.toml."""
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PUBLISH_MODES = ("dry_run", "private", "unlisted", "public")
REQUIRED = {
    "channel": ("id", "goal_subscribers", "goal_deadline"),
    "paths": ("db", "secrets", "outputs", "logs", "backups"),
    "pipeline": ("max_attempts", "retry_backoff_seconds"),
    "publishing": ("mode",),
}


def load(path=None) -> dict:
    path = Path(path or ROOT / "config" / "settings.toml").resolve()
    cfg = tomllib.loads(path.read_text())
    errors = [f"{section}.{key} is missing"
              for section, keys in REQUIRED.items()
              for key in keys if key not in cfg.get(section, {})]
    if not errors:
        if cfg["publishing"]["mode"] not in PUBLISH_MODES:
            errors.append(f"publishing.mode must be one of {PUBLISH_MODES}")
        attempts = cfg["pipeline"]["max_attempts"]
        if not isinstance(attempts, int) or attempts < 1:
            errors.append("pipeline.max_attempts must be an integer >= 1")
    if errors:
        raise ValueError(f"{path}: " + "; ".join(errors))
    root = path.parent.parent  # config/settings.toml -> project root
    cfg["paths"] = {k: (root / v).resolve() for k, v in cfg["paths"].items()}
    return cfg
