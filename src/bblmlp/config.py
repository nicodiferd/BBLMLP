"""Configuration loading for BBLMLP."""
from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict


class DataConfig(BaseModel):
    warehouse_path: Path
    snapshot_dir: Path
    backfill_seasons: list[int]


class Settings(BaseModel):
    model_config = ConfigDict(extra="allow")
    data: DataConfig


def load_settings(path: str | Path = "config/settings.yaml") -> Settings:
    raw = yaml.safe_load(Path(path).read_text())
    return Settings.model_validate(raw)
