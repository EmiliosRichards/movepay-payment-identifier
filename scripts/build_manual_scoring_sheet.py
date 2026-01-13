from __future__ import annotations

import argparse
import csv
import time
from pathlib import Path
from typing import Dict, List


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Build a manual scoring worksheet from a run CSV.\n"
            "This is meant for human labeling of:\n"
            "- cart presence (has_cart / no_cart / blocked / error)\n"
            "- shop intent (can you purchase products/services, regardless of cart)\n"
        )
    )
    ap.add_argument("--in-csv", required=True, help="Input run CSV (outputs/<run>.csv)")
    ap.add_argument("--out-csv", required=True, help="Output worksheet CSV (ground_truth/<name>.csv)")
    ap.add_argument("--limit", type=int, default=0, help="Optional cap (0 = all)")
    args = ap.parse_args()

    in_path = Path(args.in_csv)
    out_path = Path(args.out_csv)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    rows = list(csv.DictReader(in_path.open("r", encoding="utf-8", newline="")))
    if args.limit and int(args.limit) > 0:
        rows = rows[: int(args.limit)]
    if not rows:
        print("No rows in input CSV.")
        return 2

    created_at = _now_iso()

    # Worksheet fields: keep model outputs for context, plus blank gt_* columns for humans.
    fieldnames = [
        "created_at",
        "name",
        "website",
        # model outputs (context)
        "model_final_platform",
        "model_other_platform_label",
        "model_shop_presence",
        "model_cart_presence",
        "model_cart_presence_source",
        "model_cart_blocked_reasons_local_json",
        "model_cart_error_local",
        "model_cart_http_status_local",
        "model_cart_blocked_reasons_playwright_json",
        "model_cart_error_playwright",
        "model_cart_http_status_playwright",
        # manual labels (fill in)
        "gt_has_cart",  # has_cart|no_cart|blocked|error|unclear
        "gt_shop_intent",  # yes|no|unclear  (purchase products/services regardless of cart)
        "gt_notes",
    ]

    out_rows: List[Dict[str, str]] = []
    for r in rows:
        out_rows.append(
            {
                "created_at": created_at,
                "name": (r.get("name") or "").strip(),
                "website": (r.get("website") or "").strip(),
                "model_final_platform": (r.get("final_platform") or "").strip(),
                "model_other_platform_label": (r.get("other_platform_label") or "").strip(),
                "model_shop_presence": (r.get("shop_presence") or "").strip(),
                "model_cart_presence": (r.get("cart_presence") or "").strip(),
                "model_cart_presence_source": (r.get("cart_presence_source") or "").strip(),
                "model_cart_blocked_reasons_local_json": (r.get("cart_blocked_reasons_local_json") or "").strip(),
                "model_cart_error_local": (r.get("cart_error_local") or "").strip(),
                "model_cart_http_status_local": (r.get("cart_http_status_local") or "").strip(),
                "model_cart_blocked_reasons_playwright_json": (r.get("cart_blocked_reasons_playwright_json") or "").strip(),
                "model_cart_error_playwright": (r.get("cart_error_playwright") or "").strip(),
                "model_cart_http_status_playwright": (r.get("cart_http_status_playwright") or "").strip(),
                "gt_has_cart": "",
                "gt_shop_intent": "",
                "gt_notes": "",
            }
        )

    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for rr in out_rows:
            w.writerow(rr)

    print(f"Wrote manual scoring sheet: {out_path} (rows={len(out_rows)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

