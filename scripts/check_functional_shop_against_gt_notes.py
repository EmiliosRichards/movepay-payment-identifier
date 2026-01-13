from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path
from typing import Dict, List, Tuple

from shoptech_eval.shop_functionality import detect_shop_functionality


def _label_from_notes(notes: str) -> str:
    """
    Heuristic label extractor from gt_notes for quick validation.
    Returns: has_cart_checkout | no_cart_checkout | "" (unknown)
    """
    s = (notes or "").strip().lower()
    if not s:
        return ""

    has_cart = (
        "cart present",
        "cart/checkout",
        "with cart",
        "checkout",
        "active shop with cart",
        "confirmed active shop with cart/checkout",
    )
    no_cart = (
        "appointments only",
        "appointment only",
        "no transactional shop",
        "booked via external",
        "external platform",
        "donations via external",
        "order by phone",
        "order by mail",
        "order by email",
        "no cart",
        "no checkout",
        "no shop",
        "ghost/unused",
    )

    if any(k in s for k in has_cart):
        return "has_cart_checkout"
    if any(k in s for k in no_cart):
        return "no_cart_checkout"
    return ""


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Quick check: run the API-free cart/checkout detector and compare against a heuristic label extracted from gt_notes.\n"
            "This is approximate (notes vary), but useful for directionality."
        )
    )
    ap.add_argument("--gt-csv", required=True, help="Ground truth CSV (must include gt_notes)")
    ap.add_argument("--limit", type=int, default=0, help="Optional cap (0=all)")
    ap.add_argument("--sleep", type=float, default=0.0, help="Sleep seconds between sites (default 0)")
    ap.add_argument("--out-csv", default="", help="Optional output CSV with per-row results")
    ap.add_argument(
        "--skip-blocked",
        action="store_true",
        default=False,
        help="If set, exclude blocked/error predictions from accuracy numerator/denominator (treat as unscorable).",
    )
    args = ap.parse_args()

    rows = list(csv.DictReader(Path(args.gt_csv).open("r", encoding="utf-8", newline="")))
    if args.limit and int(args.limit) > 0:
        rows = rows[: int(args.limit)]

    compared = 0
    correct = 0
    mismatches: List[Tuple[str, str, str, str, List[str]]] = []
    out_rows: List[Dict[str, str]] = []

    for r in rows:
        website = (r.get("website") or "").strip()
        name = (r.get("name") or "").strip()
        notes = (r.get("gt_notes") or "").strip()
        gt = _label_from_notes(notes)
        if not website or not gt:
            continue

        res = detect_shop_functionality(website, follow_links=True)
        pred = res.presence
        if args.skip_blocked and pred in ("blocked", "error"):
            # Still log the row, but do not include in scoring.
            pass
        else:
            compared += 1
            if pred == gt:
                correct += 1
            else:
                mismatches.append((name, website, gt, pred, (res.signals or [])[:6]))

        out_rows.append(
            {
                "name": name,
                "website": website,
                "gt_notes": notes,
                "gt_cart_label_from_notes": gt,
                "pred_functional_shop_presence": pred,
                "pred_signals_json": json.dumps(res.signals or [], ensure_ascii=False),
                "pred_checked_urls_json": json.dumps(res.checked_urls or [], ensure_ascii=False),
                "pred_error": res.error or "",
                "pred_http_status": "" if res.http_status is None else str(res.http_status),
                "pred_blocked_reasons_json": json.dumps(res.blocked_reasons or [], ensure_ascii=False),
            }
        )

        if args.sleep and float(args.sleep) > 0:
            time.sleep(float(args.sleep))

    print(f"rows_in_csv: {len(rows)}")
    print(f"rows_with_heuristic_gt_label: {compared}")
    if compared:
        print(f"accuracy_vs_notes_heuristic: {correct}/{compared} ({(100.0 * correct / compared):.1f}%)")
    if mismatches:
        print("\nSample mismatches (up to 10):")
        for m in mismatches[:10]:
            print(f"- {m[0]} | gt={m[2]} pred={m[3]} | signals={m[4]}")

    if args.out_csv:
        out_path = Path(args.out_csv)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()) if out_rows else ["website"])
            w.writeheader()
            for rr in out_rows:
                w.writerow(rr)
        print(f"\nWrote: {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

