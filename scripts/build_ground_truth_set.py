from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path
from typing import Any, Dict, List

from shoptech_eval.fingerprinting import FingerprintResult, fingerprint_platform


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Build a manual ground-truth worksheet from an outputs CSV.\n"
            "This fetches HTML directly (no OpenAI) and records strong platform markers.\n"
            "It writes a CSV with blank gt_* columns for human labeling."
        )
    )
    ap.add_argument("--in-csv", required=True, help="Input run CSV (outputs/<run>.csv)")
    ap.add_argument("--out-csv", required=True, help="Output ground truth worksheet CSV (e.g. ground_truth/<name>.csv)")
    ap.add_argument("--limit", type=int, default=0, help="Optional cap on number of rows (0 = all)")
    ap.add_argument("--sample", type=int, default=0, help="Randomly sample N rows (0 = disabled)")
    ap.add_argument("--seed", type=int, default=42, help="RNG seed for --sample (default 42)")
    ap.add_argument(
        "--balanced-sticky",
        action="store_true",
        default=False,
        help="If input has local_is_sticky, sample 50/50 sticky/non-sticky when using --sample.",
    )
    ap.add_argument("--sleep", type=float, default=0.2, help="Seconds to sleep between fetches (default 0.2)")
    args = ap.parse_args()

    in_path = Path(args.in_csv)
    out_path = Path(args.out_csv)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    rows = list(csv.DictReader(in_path.open("r", encoding="utf-8", newline="")))

    # Optional random sampling (deterministic via seed).
    if args.sample and int(args.sample) > 0:
        import random

        k = int(args.sample)
        rng = random.Random(int(args.seed))
        if args.balanced_sticky and any("local_is_sticky" in r for r in rows):
            sticky = [r for r in rows if str(r.get("local_is_sticky") or "").strip() == "1"]
            non = [r for r in rows if str(r.get("local_is_sticky") or "").strip() != "1"]
            rng.shuffle(sticky)
            rng.shuffle(non)
            half = k // 2
            rows = sticky[:half] + non[: (k - half)]
            rng.shuffle(rows)
        else:
            rng.shuffle(rows)
            rows = rows[:k]

    if args.limit and int(args.limit) > 0:
        rows = rows[: int(args.limit)]
    if not rows:
        print("No rows in input CSV.")
        return 2

    fieldnames = [
        "created_at",
        "name",
        "website",
        # model outputs (from run)
        "model_shop_presence",
        "model_final_platform",
        "model_other_platform_label",
        "model_confidence",
        "model_evidence_tier",
        "model_detector",
        "local_is_sticky",
        "local_sticky_reasons_json",
        # independent fingerprinting
        "fp_platform",
        "fp_confidence",
        "fp_status",
        "fp_final_url",
        "fp_error",
        "fp_signals_json",
        # manual labels (fill in)
        "gt_shop_presence",
        "gt_final_platform",
        "gt_other_platform_label",
        "gt_notes",
    ]

    created_at = _now_iso()
    ok = 0
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()

        for i, r in enumerate(rows, start=1):
            website = (r.get("website") or "").strip()
            name = (r.get("name") or "").strip()
            if not website:
                continue

            fp: FingerprintResult = fingerprint_platform(website)
            out: Dict[str, Any] = {
                "created_at": created_at,
                "name": name,
                "website": website,
                "model_shop_presence": (r.get("shop_presence") or "").strip(),
                "model_final_platform": (r.get("final_platform") or "").strip(),
                "model_other_platform_label": (r.get("other_platform_label") or "").strip(),
                "model_confidence": (r.get("confidence") or "").strip(),
                "model_evidence_tier": (r.get("evidence_tier") or "").strip(),
                "model_detector": (r.get("detector") or "").strip(),
                "local_is_sticky": (r.get("local_is_sticky") or "").strip(),
                "local_sticky_reasons_json": (r.get("local_sticky_reasons_json") or "").strip(),
                "fp_platform": fp.platform,
                "fp_confidence": fp.confidence,
                "fp_status": "" if fp.status is None else str(fp.status),
                "fp_final_url": fp.final_url,
                "fp_error": fp.error,
                "fp_signals_json": json.dumps(fp.signals, ensure_ascii=False),
                "gt_shop_presence": "",
                "gt_final_platform": "",
                "gt_other_platform_label": "",
                "gt_notes": "",
            }
            w.writerow(out)
            ok += 1
            if args.sleep and float(args.sleep) > 0:
                time.sleep(float(args.sleep))

    print(f"Wrote ground truth worksheet: {out_path} (rows={ok})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


