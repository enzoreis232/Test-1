"""Configuração persistente sem segredos e validação de calibração."""
import json
from pathlib import Path

import pytest

from bacbo_analytics.config import AppConfig, user_data_dir


def test_save_load_preserves_settings_and_atomic_file(tmp_path):
    config = AppConfig(data_dir=tmp_path, region=(-200, 30, 800, 400),
                       rows=8, columns=16, colors={"P": 110.0, "B": 0.0, "T": 60.0},
                       first_run=False)
    config.save()
    loaded = AppConfig.load(tmp_path)
    assert loaded.region == (-200, 30, 800, 400)
    assert loaded.rows == 8
    assert loaded.colors == config.colors
    assert loaded.first_run is False
    assert not (tmp_path / "settings.tmp").exists()
    payload = json.loads((tmp_path / "settings.json").read_text())
    assert not any("token" in key.lower() for key in payload)


def test_invalid_save_does_not_overwrite_existing_settings(tmp_path):
    config = AppConfig(data_dir=tmp_path)
    config.save()
    path = tmp_path / "settings.json"
    original = path.read_bytes()
    config.rows = 0
    with pytest.raises(ValueError):
        config.save()
    assert path.read_bytes() == original


def test_load_does_not_trust_stored_data_directory(tmp_path):
    (tmp_path / "settings.json").write_text(json.dumps({"data_dir": "/unwanted/location", "rows": 8}))
    config = AppConfig.load(tmp_path)
    assert config.data_dir == tmp_path
    assert config.rows == 8


def test_missing_settings_uses_defaults(tmp_path):
    config = AppConfig.load(tmp_path)
    config.validate()
    assert config.data_dir == tmp_path
    assert config.first_run


def test_explicit_data_directory_override(monkeypatch, tmp_path):
    monkeypatch.setenv("BACBO_DATA_DIR", str(tmp_path))
    assert user_data_dir() == tmp_path.resolve()


@pytest.mark.parametrize(("field", "value"), [
    ("refresh_ms", 0), ("rows", 0), ("columns", 101),
    ("rows", True), ("history_max", 99), ("stats_window", 0),
    ("confirmations", 1), ("min_overlap", 0),
    ("confidence_threshold", float("nan")), ("confidence_threshold", 1.1),
    ("cell_padding", -.01), ("cell_padding", .45), ("hue_tolerance", float("nan")),
    ("hue_tolerance", 45), ("hue_tolerance", "invalid"),
    ("min_saturation", 256), ("min_value", -1),
    ("min_color_fraction", float("nan")),
    ("region", (0, 0, 0, 20)), ("region", (0, 0, 20.0, 20)),
    ("fill_order", "diagonal"), ("layout", "unknown"),
    ("tie_behavior", "ignore"), ("notifications", "yes"),
    ("colors", {"P": float("nan")}), ("colors", {"P": 180}),
    ("colors", {"UNKNOWN": 0}),
])
def test_invalid_configuration_rejected(field, value, tmp_path):
    config = AppConfig(data_dir=tmp_path)
    setattr(config, field, value)
    with pytest.raises(ValueError):
        config.validate()


def test_invalid_json_is_not_silently_overwritten(tmp_path):
    path = tmp_path / "settings.json"
    original = "{broken"
    path.write_text(original)
    with pytest.raises(json.JSONDecodeError):
        AppConfig.load(tmp_path)
    assert path.read_text() == original
