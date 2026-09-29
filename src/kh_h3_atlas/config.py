"""Pydantic config models and YAML loading."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator

DEFAULT_CONFIG = Path("config/default.yaml")


class BBox(BaseModel):
    xmin: float
    xmax: float
    ymin: float
    ymax: float


class OvertureSource(BaseModel):
    release: str = "auto"
    s3_bucket: str = "overturemaps-us-west-2"
    s3_region: str = "us-west-2"


class WorldPopSource(BaseModel):
    release: str = "R2025A"
    version: str = "v1"
    year: int | Literal["auto"] = "auto"
    resolution: Literal["100m", "1km"] = "100m"
    constrained: bool = True


class OsmSource(BaseModel):
    snapshot: str = "auto"
    region_path: str = "asia/cambodia"


class Sources(BaseModel):
    overture: OvertureSource = OvertureSource()
    worldpop: WorldPopSource = WorldPopSource()
    osm: OsmSource = OsmSource()


class H3Config(BaseModel):
    resolutions: list[int] = [7, 8, 9]
    poi_index_res: int = 11

    @field_validator("resolutions")
    @classmethod
    def _valid_res(cls, v: list[int]) -> list[int]:
        if not v or any(r < 0 or r > 15 for r in v):
            raise ValueError("H3 resolutions must be in 0..15")
        return sorted(set(v))


class GridConfig(BaseModel):
    # center: cell kept if its centroid is inside the polygon (drops coastal/border cells
    # and islands smaller than a cell); overlap: kept if it touches the polygon at all.
    containment: Literal["center", "overlap"] = "overlap"
    buffer_m: float = 0


class PoiConfig(BaseModel):
    min_confidence: float = Field(0.6, ge=0, le=1)
    use: dict[Literal["osm", "overture", "fsq"], bool] = {"osm": True, "overture": True}


class FeaturesConfig(BaseModel):
    neighborhood_k: list[int] = [1, 2]
    coverage_flag_min_pop: float = 200


class OutputConfig(BaseModel):
    gpkg: bool = True
    geoparquet: bool = True
    csv: bool = True
    qgis_project: bool = True


class Paths(BaseModel):
    raw: Path = Path("data/raw")
    interim: Path = Path("data/interim")
    processed: Path = Path("data/processed")


class Config(BaseModel):
    country_iso2: str = "KH"
    country_iso3: str = "KHM"
    reference_date: date
    max_source_lag_days: int = 45
    bbox: BBox
    sources: Sources = Sources()
    h3: H3Config = H3Config()
    grid: GridConfig = GridConfig()
    poi: PoiConfig = PoiConfig()
    features: FeaturesConfig = FeaturesConfig()
    output: OutputConfig = OutputConfig()
    paths: Paths = Paths()

    @property
    def worldpop_year(self) -> int:
        y = self.sources.worldpop.year
        return self.reference_date.year if y == "auto" else y

    def hash(self) -> str:
        """Stable short hash of the effective config, recorded in the manifest."""
        blob = json.dumps(self.model_dump(mode="json"), sort_keys=True).encode()
        return hashlib.sha256(blob).hexdigest()[:12]


def load_config(path: Path | str = DEFAULT_CONFIG) -> Config:
    with open(path) as f:
        return Config.model_validate(yaml.safe_load(f))
