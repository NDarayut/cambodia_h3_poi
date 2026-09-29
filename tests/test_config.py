import pytest
from pydantic import ValidationError

from kh_h3_atlas.config import Config, load_config


def test_default_config_loads():
    cfg = load_config("config/default.yaml")
    assert cfg.h3.resolutions == [8]
    assert cfg.worldpop_year == cfg.reference_date.year
    assert len(cfg.hash()) == 12


def test_invalid_resolution_rejected():
    raw = load_config("config/default.yaml").model_dump()
    raw["h3"]["resolutions"] = [16]
    with pytest.raises(ValidationError):
        Config.model_validate(raw)
