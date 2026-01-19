from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Tuple


def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for i, line in enumerate(f, start=1):
            s = (line or "").strip()
            if not s:
                continue
            try:
                rows.append(json.loads(s))
            except Exception as e:
                raise SystemExit(f"Invalid JSON on line {i} of {path}: {e}")
    return rows


def _parse_json_list(s: str) -> List[Any]:
    if not (s or "").strip():
        return []
    try:
        v = json.loads(s)
        return v if isinstance(v, list) else []
    except Exception:
        return []


def _key(r: Dict[str, Any]) -> Tuple[str, str]:
    return (str(r.get("website") or "").strip(), str(r.get("name") or "").strip())


def main() -> int:
    ap = argparse.ArgumentParser(description="Verify that a run JSONL and CSV line up.")
    ap.add_argument("--jsonl", required=True, help="Path to run JSONL (outputs/<run>.jsonl)")
    ap.add_argument("--csv", required=True, help="Path to run CSV (outputs/<run>.csv)")
    ap.add_argument("--expect-local-only", action="store_true", help="Assert zero OpenAI usage + detector=local everywhere")
    ap.add_argument("--max-mismatches", type=int, default=20, help="Max mismatches to print (default 20)")
    args = ap.parse_args()

    p_jsonl = Path(args.jsonl)
    p_csv = Path(args.csv)

    jsonl_rows = _load_jsonl(p_jsonl)
    csv_rows = list(csv.DictReader(p_csv.open("r", encoding="utf-8", newline="")))

    problems: List[str] = []

    # 1) Count alignment
    if len(csv_rows) != len(jsonl_rows):
        problems.append(f"Row count mismatch: jsonl={len(jsonl_rows)} csv={len(csv_rows)}")

    # 2) Key alignment (multiset)
    jsonl_keys = [(_key(r)) for r in jsonl_rows]
    csv_keys = [(_key(r)) for r in csv_rows]
    c_jsonl = Counter(jsonl_keys)
    c_csv = Counter(csv_keys)
    if c_jsonl != c_csv:
        # summarize differences
        only_jsonl = list((c_jsonl - c_csv).items())[: args.max_mismatches]
        only_csv = list((c_csv - c_jsonl).items())[: args.max_mismatches]
        problems.append(f"Key multiset mismatch (showing up to {args.max_mismatches} diffs).")
        if only_jsonl:
            problems.append(f"  Present in JSONL only: {only_jsonl}")
        if only_csv:
            problems.append(f"  Present in CSV only: {only_csv}")

    # 3) Build lookup for field comparisons
    jmap: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    cmap: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for r in jsonl_rows:
        jmap[_key(r)].append(r)
    for r in csv_rows:
        cmap[_key(r)].append(r)

    fields = [
        "shop_presence",
        "final_platform",
        "other_platform_label",
        "confidence",
        "evidence_tier",
        "detector",
        "error",
    ]

    mismatches = 0
    for k, jlist in jmap.items():
        clist = cmap.get(k) or []
        n = min(len(jlist), len(clist))
        for i in range(n):
            jr = jlist[i]
            cr = clist[i]
            for f in fields:
                jv = str(jr.get(f) or "").strip()
                cv = str(cr.get(f) or "").strip()
                if jv != cv:
                    mismatches += 1
                    if mismatches <= args.max_mismatches:
                        problems.append(f"Mismatch {k} field={f} jsonl={jv!r} csv={cv!r}")

            # signals list consistency
            j_sig = jr.get("signals") or []
            if not isinstance(j_sig, list):
                j_sig = []
            c_sig = _parse_json_list(str(cr.get("signals_json") or ""))
            if len(j_sig) != len(c_sig):
                mismatches += 1
                if mismatches <= args.max_mismatches:
                    problems.append(f"Mismatch {k} signals length jsonl={len(j_sig)} csv={len(c_sig)}")

            # local-only invariants
            if args.expect_local_only:
                if str(cr.get("detector") or "").strip().lower() != "local":
                    mismatches += 1
                    if mismatches <= args.max_mismatches:
                        problems.append(f"Expected local-only but detector!=local for {k}")
                if int(float(cr.get("token_cost_usd") or 0.0)) != 0 or float(cr.get("token_cost_usd") or 0.0) != 0.0:
                    mismatches += 1
                    if mismatches <= args.max_mismatches:
                        problems.append(f"Expected local-only but token_cost_usd!=0 for {k}")
                if int(cr.get("web_search_calls") or 0) != 0:
                    mismatches += 1
                    if mismatches <= args.max_mismatches:
                        problems.append(f"Expected local-only but web_search_calls!=0 for {k}")

    if problems:
        print("VERIFY FAILED")
        for p in problems[: args.max_mismatches]:
            print(p)
        # show quick summaries
        print("\nSummary:")
        print("jsonl_rows", len(jsonl_rows))
        print("csv_rows", len(csv_rows))
        print("unique_keys_jsonl", len(set(jsonl_keys)))
        print("unique_keys_csv", len(set(csv_keys)))
        return 2

    print("VERIFY OK")
    print("jsonl_rows", len(jsonl_rows))
    print("csv_rows", len(csv_rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

