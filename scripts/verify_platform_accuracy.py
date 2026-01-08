from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path
from typing import Dict, List

from shoptech_eval.fingerprinting import fingerprint_platform


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Best-effort accuracy check: compare model outputs in a run CSV against independent HTML fingerprinting.\n"
            "This is not perfect ground truth (JS-heavy sites may be inconclusive), but it catches many obvious mislabels."
        )
    )
    ap.add_argument("--csv", required=True, help="Path to outputs CSV (e.g. outputs/<run>.csv)")
    ap.add_argument("--limit", type=int, default=0, help="Optional cap on number of rows to verify (0 = all)")
    args = ap.parse_args()

    rows = list(csv.DictReader(Path(args.csv).open("r", encoding="utf-8", newline="")))
    if args.limit and int(args.limit) > 0:
        rows = rows[: int(args.limit)]

    if not rows:
        print("No rows found.")
        return 2

    compared = 0
    conclusive = 0
    agree = 0
    disagree = 0
    fp_dist = Counter()
    model_dist = Counter()
    inconclusive = 0
    errors = 0

    disagreements: List[Dict[str, str]] = []

    for r in rows:
        website = (r.get("website") or r.get("input_url") or "").strip()
        model = (r.get("final_platform") or "").strip().lower()
        if not website:
            continue
        compared += 1
        model_dist[model or ""] += 1

        fp = fingerprint_platform(website)
        fp_dist[fp.platform] += 1

        if fp.platform in ("error",):
            errors += 1
            continue
        if fp.platform in ("inconclusive",):
            inconclusive += 1
            continue

        # Conclusive for our purposes: matches one of the core platforms or "other" (wordpress heuristic)
        conclusive += 1
        if fp.platform == model:
            agree += 1
        else:
            disagree += 1
            disagreements.append(
                {
                    "website": website,
                    "model": model,
                    "fingerprint": fp.platform,
                    "fp_conf": fp.confidence,
                    "fp_shop_hint": fp.shop_presence_hint,
                    "fp_signals": "; ".join(fp.signals[:6]),
                }
            )

    print(f"rows_in_csv: {len(rows)}")
    print(f"verified_rows_attempted: {compared}")
    print(f"fingerprint_conclusive: {conclusive} ({(100.0*conclusive/compared):.1f}% of attempted)" if compared else "fingerprint_conclusive: 0")
    print(f"fingerprint_inconclusive: {inconclusive}")
    print(f"fingerprint_errors: {errors}")
    if conclusive:
        print(f"agreement_on_conclusive: {agree}/{conclusive} ({(100.0*agree/conclusive):.1f}%)")
    print("\nModel distribution:", dict(model_dist))
    print("Fingerprint distribution:", dict(fp_dist))

    if disagreements:
        print("\nTop disagreements (up to 10):")
        for d in disagreements[:10]:
            print(
                f"- {d['website']}  model={d['model']}  fp={d['fingerprint']}  shop_hint={d['fp_shop_hint']}  signals={d['fp_signals']}"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())


