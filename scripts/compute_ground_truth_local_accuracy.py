from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path

from shoptech_eval.local_detector import detect_platform_local
from shoptech_eval.fingerprinting import fingerprint_platform


def _confusion(rows, pred_key: str, gt_key: str):
    m = defaultdict(lambda: defaultdict(int))
    labels = set()
    total = 0
    correct = 0
    for r in rows:
        gt = (r.get(gt_key) or "").strip().lower()
        pred = (r.get(pred_key) or "").strip().lower()
        if not gt:
            continue
        if pred == "":
            pred = "unknown"
        total += 1
        if pred == gt:
            correct += 1
        m[gt][pred] += 1
        labels.add(gt)
        labels.add(pred)
    return total, correct, m, sorted(labels)


def main() -> int:
    ap = argparse.ArgumentParser(description="Compute local-detector and fingerprint-only accuracy vs ground truth CSV.")
    ap.add_argument("--csv", required=True, help="Ground truth CSV path (with gt_* columns filled)")
    ap.add_argument("--limit", type=int, default=0, help="Optional cap (0=all)")
    args = ap.parse_args()

    p = Path(args.csv)
    rows = list(csv.DictReader(p.open("r", encoding="utf-8", newline="")))
    if args.limit and int(args.limit) > 0:
        rows = rows[: int(args.limit)]

    # Compute predictions on the fly (don’t rely on fp_* columns; they may be stale after code changes)
    enriched = []
    for r in rows:
        website = (r.get("website") or "").strip()
        if not website:
            continue
        # Fingerprint-only (single URL)
        fp = fingerprint_platform(website)
        # Local detector (dns + link crawl + subdomains)
        ld = detect_platform_local(website).model_result
        out = dict(r)
        out["pred_fp_platform"] = fp.platform
        out["pred_fp_shop_presence"] = "shop" if fp.platform in ("woocommerce", "shopify", "shopware", "magento") else "not_shop"
        out["pred_local_platform"] = str(ld.get("final_platform") or "")
        out["pred_local_shop_presence"] = str(ld.get("shop_presence") or "")
        enriched.append(out)

    total_p, correct_p, mat_p, labels_p = _confusion(enriched, "pred_fp_platform", "gt_final_platform")
    total_lp, correct_lp, mat_lp, labels_lp = _confusion(enriched, "pred_local_platform", "gt_final_platform")
    total_ps, correct_ps, mat_ps, labels_ps = _confusion(enriched, "pred_fp_shop_presence", "gt_shop_presence")
    total_ls, correct_ls, mat_ls, labels_ls = _confusion(enriched, "pred_local_shop_presence", "gt_shop_presence")

    def print_matrix(title: str, total: int, correct: int, mat, labels):
        print(f"\n{title}")
        if total == 0:
            print("No labeled rows.")
            return
        print(f"Accuracy: {correct}/{total} ({(100.0*correct/total):.1f}%)")
        header = "GT \\ Pred".ljust(15) + "".join(l.rjust(12) for l in labels)
        print(header)
        for gt in labels:
            row = gt.ljust(15)
            for pred in labels:
                row += str(mat[gt][pred]).rjust(12)
            print(row)

    print_matrix("Fingerprint-only platform", total_p, correct_p, mat_p, labels_p)
    print_matrix("Local-detector platform", total_lp, correct_lp, mat_lp, labels_lp)
    print_matrix("Fingerprint-only shop_presence", total_ps, correct_ps, mat_ps, labels_ps)
    print_matrix("Local-detector shop_presence", total_ls, correct_ls, mat_ls, labels_ls)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())


