"""POI category groups from config/poi_categories.yaml, compiled to a SQL CASE expression."""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import BaseModel

DEFAULT_CATEGORIES = Path("config/poi_categories.yaml")
_PATTERN = re.compile(r"^[a-z_:]+=[\w:*-]+$")


class GroupPatterns(BaseModel):
    osm: list[str] = []


class CategoryGroups(BaseModel):
    groups: dict[str, GroupPatterns]


def load_groups(path: Path | str = DEFAULT_CATEGORIES) -> dict[str, list[str]]:
    """Ordered {group: [osm patterns]}; validates pattern syntax."""
    with open(path) as f:
        cg = CategoryGroups.model_validate(yaml.safe_load(f))
    out = {}
    for name, g in cg.groups.items():
        if not re.fullmatch(r"[a-z_]+", name):
            raise ValueError(f"group name {name!r} must be lowercase letters/underscores")
        for p in g.osm:
            if not _PATTERN.match(p):
                raise ValueError(f"group {name}: bad OSM pattern {p!r} (want key=value or key=*)")
        out[name] = g.osm
    return out


def group_case_sql(groups: dict[str, list[str]], column: str = "category") -> str:
    """CASE expression mapping a category to its first matching group (NULL if none)."""
    whens = []
    for name, patterns in groups.items():
        exact = [p for p in patterns if not p.endswith("=*")]
        prefixes = [p[:-1] for p in patterns if p.endswith("=*")]
        conds = []
        if exact:
            conds.append(f"{column} IN ({', '.join(repr(p) for p in exact)})")
        conds += [f"starts_with({column}, {p!r})" for p in prefixes]
        if conds:
            whens.append(f"WHEN {' OR '.join(conds)} THEN '{name}'")
    return f"CASE {' '.join(whens)} END" if whens else "NULL"
