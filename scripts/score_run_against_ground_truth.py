from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse


def _norm(u: str) -> str:
    s = (u or "").strip()
    if not s:
        return ""
    # If the field includes "url<TAB>name" or "url name", keep only the first token.
    if "\t" in s:
        s = s.split("\t", 1)[0].strip()
    else:
        # Avoid accidentally swallowing spaces in malformed inputs; URLs should not contain spaces.
        s = s.split(" ", 1)[0].strip()
    if s.lower().startswith(("http://", "https://")):
        try:
            p = urlparse(s)
            s = (p.netloc or "") + (p.path or "")
        except Exception:
            pass
    return s.strip().rstrip("/").lower()


def _load_gt(path: Path) -> dict[str, dict[str, str]]:
    rows = list(csv.DictReader(path.open("r", encoding="utf-8", newline="")))
    out: dict[str, dict[str, str]] = {}
    for r in rows:
        k = _norm(r.get("website") or "")
        if not k:
            continue
        out[k] = {
            "gt_shop_presence": (r.get("gt_shop_presence") or "").strip().lower(),
            "gt_final_platform": (r.get("gt_final_platform") or "").strip().lower(),
        }
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Score a run CSV against a ground-truth CSV (match by normalized website).")
    ap.add_argument("--run-csv", required=True, help="outputs/<run>.csv")
    ap.add_argument("--gt-csv", required=True, help="ground_truth/<gt>.csv")
    ap.add_argument("--subset", default="all", help="all|openai|local (based on run csv 'detector' column)")
    args = ap.parse_args()

    gt = _load_gt(Path(args.gt_csv))
    run_rows = list(csv.DictReader(Path(args.run_csv).open("r", encoding="utf-8", newline="")))

    total = 0
    correct_p = 0
    correct_s = 0

    conf_p = defaultdict(lambda: defaultdict(int))
    conf_s = defaultdict(lambda: defaultdict(int))

    missing_gt = 0

    subset = (args.subset or "all").strip().lower()
    for r in run_rows:
        det = (r.get("detector") or "").strip().lower()
        if subset in ("openai", "local") and det != subset:
            continue

        website = (r.get("website") or r.get("input_url") or "").strip()
        k = _norm(website)
        if not k or k not in gt:
            missing_gt += 1
            continue

        g = gt[k]
        gt_p = g["gt_final_platform"]
        gt_s = g["gt_shop_presence"]
        if not gt_p or not gt_s:
            missing_gt += 1
            continue

        pred_p = (r.get("final_platform") or "").strip().lower()
        pred_s = (r.get("shop_presence") or "").strip().lower()

        total += 1
        conf_p[gt_p][pred_p] += 1
        conf_s[gt_s][pred_s] += 1
        if pred_p == gt_p:
            correct_p += 1
        if pred_s == gt_s:
            correct_s += 1

    print(f"subset: {subset}")
    print(f"matched_rows: {total}")
    print(f"missing_or_unlabeled_gt: {missing_gt}")
    if total:
        print(f"platform_accuracy: {correct_p}/{total} ({(100.0*correct_p/total):.1f}%)")
        print(f"shop_presence_accuracy: {correct_s}/{total} ({(100.0*correct_s/total):.1f}%)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())


