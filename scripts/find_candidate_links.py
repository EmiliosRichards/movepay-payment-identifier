from __future__ import annotations

import argparse
import json
import re
import ssl
import urllib.parse
import urllib.request
from typing import List


def _fetch(url: str, *, timeout_seconds: float = 12.0, max_bytes: int = 700_000) -> tuple[str, str]:
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 shoptech/1.0"})
    with urllib.request.urlopen(req, timeout=float(timeout_seconds), context=ssl.create_default_context()) as r:
        final = r.geturl()
        html = (r.read(int(max_bytes)) or b"").decode("utf-8", errors="replace")
    return final, html


def main() -> int:
    ap = argparse.ArgumentParser(description="Extract candidate links from a page by keyword (e.g. donate/spenden).")
    ap.add_argument("url", help="URL or domain")
    ap.add_argument(
        "--keywords",
        default="spend,spende,spenden,donat,donate",
        help="Comma-separated keywords to match within href (default: donate/spenden variants)",
    )
    ap.add_argument("--limit", type=int, default=50, help="Max links to print (default 50)")
    args = ap.parse_args()

    base, html = _fetch(args.url)
    kws = [k.strip().lower() for k in (args.keywords or "").split(",") if k.strip()]
    if not kws:
        kws = ["donate"]

    hrefs = re.findall(r"""href\s*=\s*["']([^"']+)["']""", html, flags=re.I)
    out: List[str] = []
    for href in hrefs:
        low = (href or "").lower()
        if any(k in low for k in kws):
            u = urllib.parse.urljoin(base, href)
            if u not in out:
                out.append(u)

    print(json.dumps({"base": base, "count": len(out), "links": out[: max(1, int(args.limit))]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


