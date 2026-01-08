from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median
from typing import Any, Dict, Iterable, List, Tuple


def _parse_int(v: Any) -> int:
    try:
        return int(float(v))
    except Exception:
        return 0


def _parse_float(v: Any) -> float:
    try:
        return float(v)
    except Exception:
        return 0.0


def _load(path: Path) -> List[Dict[str, str]]:
    return list(csv.DictReader(path.open("r", encoding="utf-8", newline="")))


def _dist(rows: List[Dict[str, str]], key: str) -> Dict[str, int]:
    return dict(sorted(Counter((r.get(key) or "") for r in rows).items()))


def _num(rows: List[Dict[str, str]], key: str) -> List[float]:
    return [_parse_float(r.get(key)) for r in rows]


def _summary(rows: List[Dict[str, str]]) -> Dict[str, Any]:
    n = len(rows)
    cost = _num(rows, "cost_usd")
    token = _num(rows, "token_cost_usd")
    ws = _num(rows, "web_search_tool_cost_usd")
    calls = [_parse_int(r.get("web_search_calls")) for r in rows]
    retry = [_parse_int(r.get("retry_used")) for r in rows]
    low = sum(1 for r in rows if (r.get("confidence") or "").strip().lower() == "low")
    return {
        "n": n,
        "cost_total": sum(cost),
        "cost_mean": mean(cost) if cost else 0.0,
        "token_total": sum(token),
        "ws_total": sum(ws),
        "ws_calls_total": sum(calls),
        "ws_calls_mean": (sum(calls) / n) if n else 0.0,
        "retry_rate": (sum(retry) / n) if n else 0.0,
        "low_rate": (low / n) if n else 0.0,
    }


def _pct(x: float) -> str:
    return f"{100.0*x:.1f}%"


def main() -> int:
    ap = argparse.ArgumentParser(description="Compare two SHOPTECH run CSVs side-by-side.")
    ap.add_argument("--base", required=True, help="Baseline run CSV path")
    ap.add_argument("--new", required=True, help="New run CSV path")
    args = ap.parse_args()

    base = _load(Path(args.base))
    new = _load(Path(args.new))

    sb = _summary(base)
    sn = _summary(new)

    print("Rows:")
    print(f"- base: {sb['n']}")
    print(f"- new:  {sn['n']}")

    print("\nCost summary (USD):")
    print(f"- base total={sb['cost_total']:.4f} mean/row={sb['cost_mean']:.4f} (token={sb['token_total']:.4f}, web_search={sb['ws_total']:.4f})")
    print(f"- new  total={sn['cost_total']:.4f} mean/row={sn['cost_mean']:.4f} (token={sn['token_total']:.4f}, web_search={sn['ws_total']:.4f})")
    if sb["cost_total"] > 0:
        print(f"- delta total={sn['cost_total']-sb['cost_total']:.4f}  (+{(sn['cost_total']/sb['cost_total']-1)*100:.1f}%)")

    print("\nRetry + low-confidence rates:")
    print(f"- base low_rate={_pct(sb['low_rate'])} retry_rate={_pct(sb['retry_rate'])}")
    print(f"- new  low_rate={_pct(sn['low_rate'])} retry_rate={_pct(sn['retry_rate'])}")

    print("\nWeb search (billed query estimate):")
    print(f"- base total_calls={sb['ws_calls_total']} mean/row={sb['ws_calls_mean']:.3f}")
    print(f"- new  total_calls={sn['ws_calls_total']} mean/row={sn['ws_calls_mean']:.3f}")

    for key in ["final_platform", "confidence", "evidence_tier", "shop_presence", "other_platform_label"]:
        db = _dist(base, key)
        dn = _dist(new, key)
        if not any(db.values()) and not any(dn.values()):
            continue
        print(f"\nDistribution: {key}")
        print(f"- base: {db}")
        print(f"- new : {dn}")

    # Per-website change counts (best-effort)
    bmap = { (r.get('website') or ''): r for r in base if (r.get('website') or '') }
    nmap = { (r.get('website') or ''): r for r in new if (r.get('website') or '') }
    overlap = sorted(set(bmap) & set(nmap))
    if overlap:
        changed = 0
        changed_platform = 0
        changed_presence = 0
        for w in overlap:
            br, nr = bmap[w], nmap[w]
            if (br.get("final_platform") or "") != (nr.get("final_platform") or ""):
                changed_platform += 1
            if (br.get("shop_presence") or "") != (nr.get("shop_presence") or ""):
                changed_presence += 1
            if any(
                (br.get(k) or "") != (nr.get(k) or "")
                for k in ("final_platform", "confidence", "evidence_tier", "shop_presence", "other_platform_label")
            ):
                changed += 1
        print("\nOverlap by website:")
        print(f"- overlap: {len(overlap)}")
        print(f"- any_change_in_core_fields: {changed}")
        print(f"- platform_changed: {changed_platform}")
        print(f"- shop_presence_changed: {changed_presence}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())


