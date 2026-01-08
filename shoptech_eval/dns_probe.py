from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class DnsProbeResult:
    host: str
    shopify_cname: str
    raw_lines: List[str]
    error: str


_SHOPIFY_CNAME_RE = re.compile(r"(myshopify\.com|shops\.myshopify\.com)\.?", re.I)


def probe_shopify_cname(host: str) -> DnsProbeResult:
    """
    Best-effort Shopify hint via CNAME.

    Implementation notes:
    - Uses `nslookup` so it works without extra deps.
    - This is not guaranteed (some DNS setups hide CNAMEs), but when it hits it's a strong signal.
    """
    h = (host or "").strip().strip(".")
    if not h:
        return DnsProbeResult(host=host, shopify_cname="", raw_lines=[], error="empty_host")

    try:
        # Windows + mac/linux both support this flag form.
        p = subprocess.run(
            ["nslookup", "-type=CNAME", h],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        text_out = (p.stdout or "") + "\n" + (p.stderr or "")
        lines = [ln.strip() for ln in text_out.splitlines() if ln.strip()]

        # Look for myshopify targets in the output.
        hit = ""
        for ln in lines:
            m = _SHOPIFY_CNAME_RE.search(ln)
            if m:
                hit = m.group(0).rstrip(".").lower()
                break

        err = ""
        if p.returncode != 0 and not hit:
            err = f"nslookup_exit_{p.returncode}"
        return DnsProbeResult(host=h, shopify_cname=hit, raw_lines=lines[:50], error=err)
    except Exception as e:
        return DnsProbeResult(host=h, shopify_cname="", raw_lines=[], error=f"{type(e).__name__}:{e}")


