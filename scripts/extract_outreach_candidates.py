from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


def _iter_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            s = (line or "").strip()
            if not s:
                continue
            yield json.loads(s)


def _lower(s: Any) -> str:
    return str(s or "").strip().lower()


def _text_blob(o: Dict[str, Any]) -> str:
    # Compact, best-effort: use signals + reasoning as a proxy for "what the site seems to be"
    parts: List[str] = []
    sig = o.get("signals") or []
    if isinstance(sig, list):
        parts.extend([str(x) for x in sig if isinstance(x, (str, int, float))])
    parts.append(str(o.get("reasoning") or ""))
    return "\n".join(parts).lower()


_RE_DEMO = re.compile(r"\b(request|book)\s+(a\s+)?demo\b|\bfree\s+trial\b", re.I)
_RE_PRICING = re.compile(r"\bpricing\b|\bplans?\b|\bsubscription\b", re.I)
_RE_PRODUCT = re.compile(r"\bproducts?\b", re.I)
_RE_POSITIVE_ECOM = re.compile(r"\b(add\s+to\s+cart|buy\s+now|shop\s+now|order\s+now)\b", re.I)
_RE_NEG_ECOM = re.compile(
    r"\b(no|without|lacks?)\b.{0,40}\b(shop|store|webshop|cart|checkout|e-?commerce)\b", re.I
)


def _classify_outreach(text_blob: str) -> Tuple[str, str]:
    """
    Returns (outreach_relevance, outreach_reason)
    outreach_relevance: yes|maybe|no
    """
    reasons: List[str] = []

    if _RE_DEMO.search(text_blob) or _RE_PRICING.search(text_blob):
        reasons.append("saas_or_paid_service_signals")
        return "yes", "+".join(reasons)

    if _RE_POSITIVE_ECOM.search(text_blob):
        reasons.append("positive_ecom_cta_present")
        return "yes", "+".join(reasons)

    if _RE_PRODUCT.search(text_blob):
        # A lot of Apollo rows are "product companies" without an online shop.
        # This is still useful for outreach, but should not be treated as ecommerce-positive.
        reasons.append("product_language_present")
        if _RE_NEG_ECOM.search(text_blob):
            reasons.append("negated_shop_language_present")
        return "maybe", "+".join(reasons)

    if _RE_NEG_ECOM.search(text_blob):
        return "no", "negated_shop_language_present"

    return "no", "no_clear_commercial_signals"


def _extract_candidate_shop_urls(local_debug: Dict[str, Any]) -> List[str]:
    urls: List[str] = []
    attempts = local_debug.get("attempts") or []
    for a in attempts:
        if not isinstance(a, dict):
            continue
        u = str(a.get("url") or "").strip()
        if not u:
            continue
        lu = u.lower()
        if (
            "://shop." in lu
            or "://store." in lu
            or "://webshop." in lu
            or lu.endswith("/shop")
            or lu.endswith("/shop/")
            or lu.endswith("/store")
            or lu.endswith("/store/")
            or lu.endswith("/webshop")
            or lu.endswith("/webshop/")
        ):
            urls.append(u)
    # De-dupe while preserving order
    seen = set()
    out: List[str] = []
    for u in urls:
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Extract an outreach-focused CSV from a run JSONL.\n"
            "This is meant to help keep 'commercially relevant' companies visible even when shop_presence=not_shop.\n"
        )
    )
    ap.add_argument("--in-jsonl", required=True, help="Input run JSONL (outputs/<run>.jsonl)")
    ap.add_argument("--out-csv", required=True, help="Output outreach candidates CSV (outputs/<run>_outreach.csv)")
    ap.add_argument("--min-relevance", default="maybe", choices=["yes", "maybe", "no"])
    args = ap.parse_args()

    in_path = Path(args.in_jsonl)
    out_path = Path(args.out_csv)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    thresh = {"no": 0, "maybe": 1, "yes": 2}[str(args.min_relevance)]

    fieldnames = [
        "name",
        "website",
        "shop_presence",
        "final_platform",
        "other_platform_label",
        "confidence",
        "detector",
        "local_is_sticky",
        "local_sticky_reasons_json",
        "outreach_relevance",
        "outreach_reason",
        "candidate_shop_urls_json",
    ]

    out_rows: List[Dict[str, str]] = []
    for o in _iter_jsonl(in_path):
        name = str(o.get("name") or "").strip()
        website = str(o.get("website") or "").strip()
        shop_presence = str(o.get("shop_presence") or "").strip()
        final_platform = str(o.get("final_platform") or "").strip()
        other_platform_label = str(o.get("other_platform_label") or "").strip()
        confidence = str(o.get("confidence") or "").strip()
        detector = str(o.get("detector") or "").strip()

        local_debug = o.get("local_debug") or {}
        if not isinstance(local_debug, dict):
            local_debug = {}
        sticky = local_debug.get("sticky") or {}
        if not isinstance(sticky, dict):
            sticky = {}

        local_is_sticky = "1" if bool(sticky.get("is_sticky", False)) else "0"
        reasons = sticky.get("reasons") or []
        if not isinstance(reasons, list):
            reasons = []

        blob = _text_blob(o)
        rel, rel_reason = _classify_outreach(blob)
        if {"no": 0, "maybe": 1, "yes": 2}[rel] < thresh:
            continue

        out_rows.append(
            {
                "name": name,
                "website": website,
                "shop_presence": shop_presence,
                "final_platform": final_platform,
                "other_platform_label": other_platform_label,
                "confidence": confidence,
                "detector": detector,
                "local_is_sticky": local_is_sticky,
                "local_sticky_reasons_json": json.dumps(reasons, ensure_ascii=False),
                "outreach_relevance": rel,
                "outreach_reason": rel_reason,
                "candidate_shop_urls_json": json.dumps(_extract_candidate_shop_urls(local_debug), ensure_ascii=False),
            }
        )

    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in out_rows:
            w.writerow(r)

    print(f"Wrote outreach candidates: {out_path} (rows={len(out_rows)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

