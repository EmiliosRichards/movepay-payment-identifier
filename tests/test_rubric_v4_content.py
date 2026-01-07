from __future__ import annotations

from pathlib import Path


def test_shop_platform_rubric_exists_and_has_expected_sections() -> None:
    p = Path("rubrics/shop_platform_rubric_v1.md")
    assert p.exists()
    text = p.read_text(encoding="utf-8")
    assert "## Evidence tiers" in text
    assert "## Decision rules" in text


def test_shop_platform_rubric_defines_platform_enum() -> None:
    text = Path("rubrics/shop_platform_rubric_v1.md").read_text(encoding="utf-8")
    for p in ("magento", "shopware", "woocommerce", "shopify", "other", "unknown"):
        assert p in text.lower()


