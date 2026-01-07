from __future__ import annotations

from shoptech_eval.schema import OUTPUT_SCHEMA, json_schema_text_config


def test_schema_has_expected_keys_only() -> None:
    props = OUTPUT_SCHEMA["properties"]
    required = set(OUTPUT_SCHEMA["required"])

    expected = {
        "input_url",
        "final_platform",
        "confidence",
        "evidence_tier",
        "signals",
        "reasoning",
    }
    assert set(props.keys()) == expected
    assert required == expected

    assert OUTPUT_SCHEMA["additionalProperties"] is False


def test_schema_text_config_shape() -> None:
    cfg = json_schema_text_config()
    assert cfg["format"]["type"] == "json_schema"
    assert cfg["format"]["name"] == "shoptech_platform_detection"
    assert cfg["format"]["strict"] is True
    assert cfg["format"]["schema"] == OUTPUT_SCHEMA


