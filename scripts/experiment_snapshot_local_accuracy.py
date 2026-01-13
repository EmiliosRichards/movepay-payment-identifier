from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

from shoptech_eval.fingerprinting import fingerprint_platform
from shoptech_eval.local_detector import detect_platform_local


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _now_stamp() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


def _safe_git_head() -> str:
    try:
        p = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        s = (p.stdout or "").strip()
        return s if s else ""
    except Exception:
        return ""


@dataclass(frozen=True)
class Metrics:
    total: int
    correct: int
    confusion: Dict[str, Dict[str, int]]


def _update_conf(mat: Dict[str, Dict[str, int]], gt: str, pred: str) -> None:
    mat.setdefault(gt, {})
    mat[gt][pred] = int(mat[gt].get(pred, 0) or 0) + 1


def _score_shop_presence(rows: List[Dict[str, str]], *, mode: str, cautious_on_sticky: bool) -> Tuple[Metrics, List[Dict[str, Any]]]:
    total = 0
    correct = 0
    confusion: Dict[str, Dict[str, int]] = {}
    per_row: List[Dict[str, Any]] = []

    for r in rows:
        website = (r.get("website") or "").strip()
        gt = (r.get("gt_shop_presence") or "").strip().lower()
        if not website or not gt:
            continue

        ld = detect_platform_local(website, shop_presence_mode=mode, cautious_on_sticky=bool(cautious_on_sticky))
        pred = str((ld.model_result or {}).get("shop_presence") or "").strip().lower() or "unknown"

        total += 1
        if pred == gt:
            correct += 1
        _update_conf(confusion, gt, pred)

        per_row.append(
            {
                "website": website,
                "name": (r.get("name") or "").strip(),
                "gt_shop_presence": gt,
                "pred_shop_presence": pred,
                "pred_final_platform": str((ld.model_result or {}).get("final_platform") or ""),
                "pred_confidence": str((ld.model_result or {}).get("confidence") or ""),
                "pred_signals_json": json.dumps((ld.model_result or {}).get("signals") or [], ensure_ascii=False),
                "sticky": int(bool(((ld.debug or {}).get("sticky") or {}).get("is_sticky", False))),
                "sticky_reasons_json": json.dumps((((ld.debug or {}).get("sticky") or {}).get("reasons") or []), ensure_ascii=False),
                "gt_notes": (r.get("gt_notes") or "").strip(),
            }
        )

    return Metrics(total=total, correct=correct, confusion=confusion), per_row


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Run a reproducible local-detector accuracy snapshot against a ground-truth CSV and save metrics + config."
    )
    ap.add_argument("--gt-csv", required=True, help="Ground truth CSV path (with gt_* columns)")
    ap.add_argument("--label", default="snapshot", help="Human label for the snapshot (used in folder name)")
    ap.add_argument(
        "--shop-presence-mode",
        default=os.environ.get("SHOPTECH_LOCAL_SHOP_PRESENCE_MODE", "installed"),
        help="installed|functional (default: env SHOPTECH_LOCAL_SHOP_PRESENCE_MODE or installed)",
    )
    ap.add_argument(
        "--cautious-on-sticky",
        action="store_true",
        default=False,
        help="In functional mode, avoid calling not_shop on sticky/protected sites (use unclear instead).",
    )
    ap.add_argument("--out-dir", default="experiments", help="Root output dir (default experiments/)")
    args = ap.parse_args()

    mode = (args.shop_presence_mode or "installed").strip().lower()
    if mode not in ("installed", "functional"):
        raise SystemExit("--shop-presence-mode must be installed|functional")

    gt_path = Path(args.gt_csv)
    rows = list(csv.DictReader(gt_path.open("r", encoding="utf-8", newline="")))

    stamp = _now_stamp()
    label = "".join(ch if (ch.isalnum() or ch in "-_") else "_" for ch in (args.label or "snapshot")).strip("_")
    out_root = Path(args.out_dir)
    out_dir = out_root / f"{stamp}_{label}_{mode}"
    out_dir.mkdir(parents=True, exist_ok=True)

    metrics, per_row = _score_shop_presence(rows, mode=mode, cautious_on_sticky=bool(args.cautious_on_sticky))

    repo_root = Path(".")
    code_hashes = {
        "git_head": _safe_git_head(),
        "shoptech_eval/local_detector.py": _sha256_file(repo_root / "shoptech_eval" / "local_detector.py"),
        "shoptech_eval/fingerprinting.py": _sha256_file(repo_root / "shoptech_eval" / "fingerprinting.py"),
    }

    cfg = {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "label": label,
        "shop_presence_mode": mode,
        "cautious_on_sticky": bool(args.cautious_on_sticky),
        "gt_csv": str(gt_path),
        "code": code_hashes,
    }

    acc = (metrics.correct / metrics.total) if metrics.total else 0.0
    summary = (
        f"Local-detector shop_presence accuracy snapshot\n"
        f"- gt_csv: {gt_path}\n"
        f"- mode: {mode}\n"
        f"- rows_scored: {metrics.total}\n"
        f"- accuracy: {metrics.correct}/{metrics.total} ({(100.0*acc):.1f}%)\n"
        f"- git_head: {code_hashes.get('git_head') or 'unknown'}\n"
    )

    (out_dir / "config.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    (out_dir / "metrics.json").write_text(json.dumps({"shop_presence": metrics.__dict__}, indent=2), encoding="utf-8")
    (out_dir / "summary.txt").write_text(summary, encoding="utf-8")

    with (out_dir / "per_row.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(per_row[0].keys()) if per_row else ["website"])
        w.writeheader()
        for r in per_row:
            w.writerow(r)

    print(summary)
    print(f"Wrote snapshot: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

