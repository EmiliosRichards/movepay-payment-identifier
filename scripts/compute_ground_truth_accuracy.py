from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description="Compute accuracy metrics from a ground-truth CSV.")
    ap.add_argument("--csv", required=True, help="Path to ground truth CSV")
    args = ap.parse_args()

    p = Path(args.csv)
    if not p.exists():
        print(f"File not found: {p}")
        return 1

    rows = list(csv.DictReader(p.open("r", encoding="utf-8", newline="")))
    if not rows:
        print("No rows found.")
        return 0

    total = 0
    correct_platform = 0
    correct_presence = 0

    # For Confusion Matrix / Precision-Recall
    # We only compute platform accuracy on rows where ground truth platform is known
    platforms = ["magento", "shopware", "woocommerce", "shopify", "other", "unknown"]
    
    # Ground Truth vs Model
    matrix = defaultdict(lambda: defaultdict(int))
    all_gt_platforms = set()
    all_model_platforms = set()

    presence_matrix = defaultdict(lambda: defaultdict(int))

    for r in rows:
        gt_p = (r.get("gt_final_platform") or "").strip().lower()
        model_p = (r.get("model_final_platform") or "").strip().lower()
        gt_s = (r.get("gt_shop_presence") or "").strip().lower()
        model_s = (r.get("model_shop_presence") or "").strip().lower()

        if not gt_p or not gt_s:
            continue
        
        total += 1
        if gt_p == model_p:
            correct_platform += 1
        if gt_s == model_s:
            correct_presence += 1
        
        matrix[gt_p][model_p] += 1
        all_gt_platforms.add(gt_p)
        all_model_platforms.add(model_p)

        presence_matrix[gt_s][model_s] += 1

    if total == 0:
        print("No labeled rows to compare.")
        return 0

    print(f"Total labeled rows: {total}")
    print(f"Platform Accuracy: {correct_platform}/{total} ({(100.0*correct_platform/total):.1f}%)")
    print(f"Shop Presence Accuracy: {correct_presence}/{total} ({(100.0*correct_presence/total):.1f}%)")

    print("\n--- Platform Confusion Matrix (Rows=GT, Cols=Model) ---")
    sorted_p = sorted(list(all_gt_platforms | all_model_platforms))
    header = "GT \\ Model".ljust(15) + "".join(p.rjust(12) for p in sorted_p)
    print(header)
    for gt in sorted_p:
        row_str = gt.ljust(15)
        for model in sorted_p:
            count = matrix[gt][model]
            row_str += str(count).rjust(12)
        print(row_str)

    print("\n--- Platform Metrics ---")
    for p in sorted_p:
        tp = matrix[p][p]
        fp = sum(matrix[other][p] for other in sorted_p if other != p)
        fn = sum(matrix[p][other] for other in sorted_p if other != p)
        
        precision = (tp / (tp + fp)) if (tp + fp) > 0 else 0
        recall = (tp / (tp + fn)) if (tp + fn) > 0 else 0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0
        
        print(f"{p.ljust(12)} | Precision: {precision:.2f} | Recall: {recall:.2f} | F1: {f1:.2f} (n={tp+fn})")

    print("\n--- Shop Presence Confusion Matrix (Rows=GT, Cols=Model) ---")
    presence_types = sorted(list(set(presence_matrix.keys()) | {m for d in presence_matrix.values() for m in d.keys()}))
    header = "GT \\ Model".ljust(15) + "".join(t.rjust(12) for t in presence_types)
    print(header)
    for gt in presence_types:
        row_str = gt.ljust(15)
        for model in presence_types:
            count = presence_matrix[gt][model]
            row_str += str(count).rjust(12)
        print(row_str)

    return 0

if __name__ == "__main__":
    import sys
    sys.exit(main())

