"""Load config.yaml (or a smaller variant that extends it) into a plain dict."""

from __future__ import annotations

import datetime as dt
import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "pipeline" / "config.yaml"


def _read(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    parent = cfg.pop("extends", None)
    if parent:
        base = _read(path.parent / parent)
        base.update(cfg)
        cfg = base
    return cfg


def load_config(path: str | Path | None = None) -> dict:
    """Read a config file, apply the SEED override and resolve paths against the repo root."""
    cfg = _read(Path(path) if path else DEFAULT_CONFIG)
    if os.environ.get("SEED"):
        cfg["seed"] = int(os.environ["SEED"])
    if isinstance(cfg["today"], str):
        cfg["today"] = dt.date.fromisoformat(cfg["today"])
    cfg["paths"] = {k: ROOT / Path(v) for k, v in cfg["paths"].items()}
    return cfg
