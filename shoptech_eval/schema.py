from __future__ import annotations

from typing import Any, Dict


OUTPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "input_url": {"type": "string"},
        # Whether the domain appears to be an ecommerce shop site or not.
        "shop_presence": {"type": "string", "enum": ["shop", "not_shop", "unclear"]},
        "final_platform": {
            "type": "string",
            "enum": ["magento", "shopware", "woocommerce", "shopify", "other", "unknown"],
        },
        # For final_platform=other, capture a short known label when identifiable (else empty).
        # Examples: "wordpress", "weblication", "aem", "wix", "squarespace", "bigcommerce", "prestashop", "custom/laravel".
        "other_platform_label": {"type": "string", "maxLength": 80},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "evidence_tier": {"type": "string", "enum": ["A", "B", "C"]},
        # Short list of key signals used for the decision (OK to be empty).
        "signals": {
            "type": "array",
            "maxItems": 8,
            "items": {"type": "string", "maxLength": 120},
        },
        # Keep short to reduce output tokens and avoid URL leakage.
        "reasoning": {"type": "string", "maxLength": 600},
    },
    "required": [
        "input_url",
        "shop_presence",
        "final_platform",
        "other_platform_label",
        "confidence",
        "evidence_tier",
        "signals",
        "reasoning",
    ],
}


OUTPUT_SCHEMA_WITH_SOURCES: Dict[str, Any] = {
    **OUTPUT_SCHEMA,
    "properties": {
        **(OUTPUT_SCHEMA.get("properties") or {}),
        # Debug-only: allow a compact sources list for auditing/search-behavior analysis.
        "sources": {
            "type": "array",
            "maxItems": 8,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "url": {"type": "string"},
                    "title": {"type": "string"},
                    "note": {"type": "string", "maxLength": 160},
                },
                # OpenAI strict JSON Schema requires that `required` includes every key in `properties`.
                # Allow empty strings for title/note if unknown.
                "required": ["url", "title", "note"],
            },
        },
    },
    "required": [*OUTPUT_SCHEMA.get("required", []), "sources"],
}


def json_schema_text_config(
    *,
    name: str = "shoptech_platform_detection",
    strict: bool = True,
    schema: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    return {
        "format": {
            "type": "json_schema",
            "name": name,
            "strict": strict,
            "schema": schema or OUTPUT_SCHEMA,
        }
    }


