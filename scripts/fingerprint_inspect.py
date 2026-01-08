from __future__ import annotations

import argparse
import json

from shoptech_eval.fingerprinting import fingerprint_platform


def main() -> int:
    ap = argparse.ArgumentParser(description="Inspect HTML fingerprint markers for one or more URLs/domains.")
    ap.add_argument("urls", nargs="+", help="One or more URLs/domains")
    args = ap.parse_args()

    for u in args.urls:
        r = fingerprint_platform(u)
        print("\nURL:", u)
        print("  final_url:", r.final_url)
        print("  status:", r.status)
        print("  platform:", r.platform)
        print("  fp_confidence:", r.confidence)
        print("  shop_presence_hint:", r.shop_presence_hint)
        print("  signals_json:", json.dumps(r.signals, ensure_ascii=False))
        if r.error:
            print("  error:", r.error)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


