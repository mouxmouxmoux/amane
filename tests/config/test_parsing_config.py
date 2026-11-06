from pathlib import Path

import pytest
from pydantic import ValidationError

from amane.config import ColdSettings, ConfigManager, ParsingConfig
from amane.parsing import Mosaic, parse_file_info


@pytest.mark.parametrize("value", ["", " ", "-", "--U", "1U", "U/C", "U\\C", "U.*", "U-C"])
def test_invalid_marker(value: str) -> None:
    for field in ("cracked_suffixes", "leaked_suffixes", "uncensored_suffixes", "subtitle_suffixes"):
        with pytest.raises(ValidationError, match=field):
            ParsingConfig.model_validate({field: [value]})


def test_marker_config_persistence(tmp_path: Path) -> None:
    cold = ColdSettings(data_dir=tmp_path)
    config = ConfigManager.with_cold(cold)
    config.update(
        {
            "parsing": {
                "cracked_suffixes": [" -xyz ", "XYZ", "xyz", "U"],
                "subtitle_suffixes": [],
                "cracked_display_name": "破解",
            }
        }
    )
    rules = config.hot.parsing.to_marker_rules()
    info = parse_file_info("MIDV-123-XYZ.mp4", marker_rules=rules)
    assert info.mosaic is Mosaic.CRACKED
    assert not info.has_subtitle
    assert config.hot.parsing.cracked_suffixes == ["XYZ", "U"]
    config.update({"parsing": {"cracked_suffixes": []}})
    reloaded = ConfigManager.with_cold(cold)
    assert reloaded.hot.parsing.cracked_suffixes == []
    assert reloaded.hot.parsing.subtitle_suffixes == []
    assert reloaded.hot.parsing.to_marker_rules().cracked_display_name == "破解"
    assert parse_file_info("MIDV-123-U.mp4", marker_rules=reloaded.hot.parsing.to_marker_rules()).mosaic is None
    persisted = cold.config_path.read_bytes()
    with pytest.raises(ValidationError, match="cracked_suffixes"):
        config.update({"parsing": {"cracked_suffixes": [".*"]}})
    assert cold.config_path.read_bytes() == persisted
    assert config.hot.parsing == reloaded.hot.parsing


def test_marker_defaults_include_legacy_and_chinese_suffixes() -> None:
    config = ParsingConfig()
    assert config.cracked_suffixes == ["U", "UC", "LTX", "破解", "克破", "CRACKED"]
    assert config.leaked_suffixes == ["流出", "留出", "LEAKED"]
    assert config.uncensored_suffixes == ["無碼", "无码", "UNCENSORED"]
    assert config.subtitle_suffixes == ["C", "UC", "字幕", "中文", "中字"]

    rules = config.to_marker_rules()
    assert parse_file_info("MIDV-123-破解.mp4", marker_rules=rules).mosaic is Mosaic.CRACKED
    assert parse_file_info("MIDV-123-留出.mp4", marker_rules=rules).mosaic is Mosaic.LEAKED
    assert parse_file_info("MIDV-123-无码.mp4", marker_rules=rules).mosaic is Mosaic.UNCENSORED
    assert parse_file_info("MIDV-123-中字.mp4", marker_rules=rules).has_subtitle_in_name
