from __future__ import annotations

import argparse
import csv
import json
import re
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


def _stats(nums: List[float]) -> Dict[str, float]:
    if not nums:
        return {"sum": 0.0, "mean": 0.0, "median": 0.0, "min": 0.0, "max": 0.0}
    return {"sum": sum(nums), "mean": mean(nums), "median": median(nums), "min": min(nums), "max": max(nums)}


def _topk(rows: List[dict], *, key, k: int = 5) -> List[dict]:
    return sorted(rows, key=key, reverse=True)[:k]


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Deep analysis for SHOPTECH platform detection runs (platform distribution, quality checks, cost + caching)."
    )
    ap.add_argument("--csv", required=True, help="Path to outputs CSV (e.g. outputs/<run>.csv)")
    ap.add_argument("--show-rows", type=int, default=8, help="How many unknown/other rows to list (default 8)")
    args = ap.parse_args()

    p = Path(args.csv)
    rows = list(csv.DictReader(p.open("r", encoding="utf-8", newline="")))
    n = len(rows)
    if n == 0:
        print("No rows found.")
        return 2

    # Core fields (tolerate missing columns).
    def col(name: str, default: str = "") -> List[str]:
        return [r.get(name, default) for r in rows]

    final_platform = col("final_platform")
    confidence = col("confidence")
    evidence_tier = col("evidence_tier")
    shop_presence = col("shop_presence")
    other_platform_label = col("other_platform_label")

    print(f"rows: {n}")

    # Distributions
    print("\nDistributions:")
    print(f"- final_platform: {dict(sorted(Counter(final_platform).items()))}")
    if any(x.strip() for x in shop_presence):
        print(f"- shop_presence:  {dict(sorted(Counter(shop_presence).items()))}")
    print(f"- confidence:     {dict(sorted(Counter(confidence).items()))}")
    print(f"- evidence_tier:  {dict(sorted(Counter(evidence_tier).items()))}")
    if any(x.strip() for x in other_platform_label):
        # show top labels (excluding empty)
        lbls = [x.strip() for x in other_platform_label if (x or "").strip()]
        if lbls:
            c = Counter(lbls)
            print(f"- other_platform_label (top): {dict(c.most_common(12))}")

    # Crosstabs
    def _crosstab(a: Iterable[str], b: Iterable[str]) -> Dict[Tuple[str, str], int]:
        out: Dict[Tuple[str, str], int] = defaultdict(int)
        for x, y in zip(a, b):
            out[(x or ""), (y or "")] += 1
        return out

    print("\nCross-tabs:")
    pc = _crosstab(final_platform, confidence)
    tc = _crosstab(evidence_tier, confidence)
    print("- platform x confidence:")
    for (p1, c1), k in sorted(pc.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        print(f"  {p1:11s} {c1:6s}: {k}")
    print("- tier x confidence:")
    for (t1, c1), k in sorted(tc.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        print(f"  {t1:2s} {c1:6s}: {k}")

    # Cost/time/token stats
    cost_usd = [_parse_float(r.get("cost_usd")) for r in rows]
    token_cost_usd = [_parse_float(r.get("token_cost_usd")) for r in rows]
    ws_cost_usd = [_parse_float(r.get("web_search_tool_cost_usd")) for r in rows]
    dur_s = [_parse_float(r.get("duration_seconds")) for r in rows]

    input_t = [_parse_int(r.get("input_tokens")) for r in rows]
    cached_t = [_parse_int(r.get("cached_input_tokens")) for r in rows]
    output_t = [_parse_int(r.get("output_tokens")) for r in rows]
    total_t = [_parse_int(r.get("total_tokens")) for r in rows]

    ws_calls = [_parse_int(r.get("web_search_calls")) for r in rows]
    ws_total = [_parse_int(r.get("web_search_tool_calls_total")) for r in rows]
    ws_q = [_parse_int(r.get("web_search_calls_query")) for r in rows]
    ws_o = [_parse_int(r.get("web_search_calls_open")) for r in rows]
    ws_u = [_parse_int(r.get("web_search_calls_unknown")) for r in rows]

    print("\nCost + timing:")
    s = _stats(cost_usd)
    print(f"- cost_usd: total={s['sum']:.4f} mean={s['mean']:.4f} median={s['median']:.4f} min={s['min']:.4f} max={s['max']:.4f}")
    s = _stats(token_cost_usd)
    print(
        f"- token_cost_usd: total={s['sum']:.4f} mean={s['mean']:.4f} median={s['median']:.4f} min={s['min']:.4f} max={s['max']:.4f}"
    )
    s = _stats(ws_cost_usd)
    print(
        f"- web_search_tool_cost_usd: total={s['sum']:.4f} mean={s['mean']:.4f} median={s['median']:.4f} min={s['min']:.4f} max={s['max']:.4f}"
    )
    s = _stats(dur_s)
    print(f"- duration_seconds: total_min={sum(dur_s)/60:.2f} mean={s['mean']:.2f} median={s['median']:.2f} min={s['min']:.2f} max={s['max']:.2f}")

    print("\nToken usage:")
    print(f"- input_tokens: mean={mean(input_t):.1f} median={median(input_t):.1f} min={min(input_t)} max={max(input_t)}")
    print(f"- cached_input_tokens: mean={mean(cached_t):.1f} median={median(cached_t):.1f} min={min(cached_t)} max={max(cached_t)}")
    print(f"- output_tokens: mean={mean(output_t):.1f} median={median(output_t):.1f} min={min(output_t)} max={max(output_t)}")
    print(f"- total_tokens: mean={mean(total_t):.1f} median={median(total_t):.1f} min={min(total_t)} max={max(total_t)}")

    cache_rates = [(c / i) for i, c in zip(input_t, cached_t) if i > 0]
    if cache_rates:
        print("\nPrompt caching effectiveness (cached_input_tokens / input_tokens):")
        print(
            f"- mean={mean(cache_rates):.3f} median={median(cache_rates):.3f} min={min(cache_rates):.3f} max={max(cache_rates):.3f} "
            f"(rows_with_cache>0: {sum(1 for x in cache_rates if x > 0)}/{len(cache_rates)})"
        )

    print("\nWeb search usage:")
    print(f"- web_search_calls (billed query est): total={sum(ws_calls)} mean={sum(ws_calls)/n:.3f} distribution={dict(sorted(Counter(ws_calls).items()))}")
    if any(ws_total):
        print(f"- web_search_tool_calls_total: total={sum(ws_total)} mean={sum(ws_total)/n:.3f}")
    if any(ws_q) or any(ws_o) or any(ws_u):
        tot = sum(ws_q) + sum(ws_o) + sum(ws_u)
        print(f"- completed by kind: query={sum(ws_q)} open={sum(ws_o)} unknown={sum(ws_u)} (kind_total={tot})")

    # Output contract checks
    reasons = col("reasoning")
    url_leaks = sum(1 for r in reasons if re.search(r"https?://", r or ""))
    too_long = sum(1 for r in reasons if len(r or "") > 600)
    print("\nOutput contract checks:")
    print(f"- reasoning contains raw URL: {url_leaks}")
    print(f"- reasoning > 600 chars: {too_long}")

    # Heuristic consistency flags (rubric alignment)
    inconsistencies: List[str] = []
    for r in rows:
        t = (r.get("evidence_tier") or "").strip()
        c = (r.get("confidence") or "").strip().lower()
        p1 = (r.get("final_platform") or "").strip().lower()
        if t == "A" and c and c != "high":
            inconsistencies.append("tier_A_not_high")
            break
    for r in rows:
        p1 = (r.get("final_platform") or "").strip().lower()
        c = (r.get("confidence") or "").strip().lower()
        if p1 == "unknown" and c and c != "low":
            inconsistencies.append("unknown_not_low")
            break
    print("\nRubric-consistency heuristics:")
    if inconsistencies:
        print(f"- flags: {sorted(set(inconsistencies))}")
    else:
        print("- flags: none")

    # Unknown/other review (names only)
    show_n = max(0, int(args.show_rows))
    interesting = [r for r in rows if (r.get("final_platform") or "").strip().lower() in ("unknown", "other")]
    if interesting:
        print(f"\nUnknown/Other rows (showing up to {show_n}):")
        for r in interesting[:show_n]:
            name = (r.get("name") or "").strip()
            fp = (r.get("final_platform") or "").strip()
            conf1 = (r.get("confidence") or "").strip()
            tier1 = (r.get("evidence_tier") or "").strip()
            print(f"- {fp:7s} conf={conf1:6s} tier={tier1:2s} name={name}")

    # Top expensive/slow rows (names only)
    rows_cost = [(r, _parse_float(r.get("cost_usd"))) for r in rows]
    rows_dur = [(r, _parse_float(r.get("duration_seconds"))) for r in rows]
    top_cost = sorted(rows_cost, key=lambda x: x[1], reverse=True)[:5]
    top_dur = sorted(rows_dur, key=lambda x: x[1], reverse=True)[:5]

    print("\nTop rows by cost_usd (names only):")
    for r, v in top_cost:
        print(f"- cost={v:.4f} platform={r.get('final_platform')} conf={r.get('confidence')} name={r.get('name')}")

    print("\nTop rows by duration_seconds (names only):")
    for r, v in top_dur:
        print(f"- dur={v:.2f}s platform={r.get('final_platform')} conf={r.get('confidence')} name={r.get('name')}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())


