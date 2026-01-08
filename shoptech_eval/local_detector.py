from __future__ import annotations

import re
import ssl
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Dict, List, Tuple

from .dns_probe import probe_shopify_cname
from .fingerprinting import fingerprint_platform


@dataclass(frozen=True)
class LocalDetectResult:
    model_result: Dict[str, object]  # schema-shaped payload
    debug: Dict[str, object]


def _normalize_url(url: str) -> str:
    u = (url or "").strip()
    if not u:
        return ""
    if not u.lower().startswith(("http://", "https://")):
        u = "https://" + u
    return u


def _host_from_url(url: str) -> str:
    try:
        u = _normalize_url(url)
        return (urllib.parse.urlparse(u).hostname or "").strip().lower()
    except Exception:
        return ""


def _fetch_html(
    url: str, *, timeout_seconds: float = 12.0, max_bytes: int = 700_000
) -> Tuple[str, int | None, str, Dict[str, str], str]:
    """Return (final_url, status_code, html_lower, headers_lower_map, error_str)."""
    u = _normalize_url(url)
    if not u:
        return "", None, "", {}, "empty_url"
    req = urllib.request.Request(
        u,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) shoptech-local-detector/1.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.8,de-DE,de;q=0.6",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=float(timeout_seconds), context=ssl.create_default_context()) as resp:
            final_url = resp.geturl() or u
            status = getattr(resp, "status", None)
            raw = resp.read(int(max_bytes)) or b""
            txt = raw.decode("utf-8", errors="replace").lower()
            headers = {str(k).lower(): str(v).lower() for k, v in (resp.headers or {}).items()}
            return final_url, int(status) if status is not None else None, txt, headers, ""
    except Exception as e:
        return u, None, "", {}, f"{type(e).__name__}:{e}"


def _extract_shop_links(base_url: str, html: str, *, limit: int = 15) -> List[str]:
    """
    Find likely shop/cart links from a homepage HTML snippet.
    This is intentionally simple and fast (no JS execution).
    """
    if not html:
        return []
    hrefs = re.findall(r"""href\s*=\s*["']([^"']+)["']""", html, flags=re.I)
    keys = ("shop", "store", "warenkorb", "cart", "checkout", "kasse", "tickets", "voucher", "gutschein")
    out: List[str] = []
    for href in hrefs:
        low = (href or "").lower()
        if any(k in low for k in keys):
            u = urllib.parse.urljoin(base_url, href)
            if u not in out:
                out.append(u)
        if len(out) >= max(1, int(limit)):
            break
    return out


def _subdomain_candidates(host: str) -> List[str]:
    h = (host or "").strip().lower().strip(".")
    if not h:
        return []
    # Also try stripping www.
    base = h[4:] if h.startswith("www.") else h
    cands = []
    for sub in ("shop", "store", "webshop"):
        cands.append(f"{sub}.{base}")
    return list(dict.fromkeys(cands))


def detect_platform_local(url: str) -> LocalDetectResult:
    """
    API-free local detector:
    - DNS hint for Shopify via CNAME
    - Direct HTML fingerprinting
    - If unclear, follow likely "shop" links and probe common shop subdomains
    """
    input_url = _normalize_url(url)
    host = _host_from_url(input_url)

    debug: Dict[str, object] = {
        "input_url": input_url,
        "host": host,
        "attempts": [],
        "sticky": {"is_sticky": False, "reasons": []},
    }

    # 1) DNS Shopify hint (fast, no HTTP)
    dns_hit = probe_shopify_cname(host) if host else None
    if dns_hit and dns_hit.shopify_cname:
        debug["dns_shopify"] = {"host": dns_hit.host, "shopify_cname": dns_hit.shopify_cname, "error": dns_hit.error}
        model_result = {
            "input_url": input_url,
            "final_platform": "shopify",
            "shop_presence": "shop",
            "other_platform_label": "",
            "confidence": "high",
            "evidence_tier": "A",
            "signals": [f"dns:cname->{dns_hit.shopify_cname}"],
            "reasoning": "DNS CNAME indicates Shopify (myshopify).",
        }
        return LocalDetectResult(model_result=model_result, debug=debug)

    # 2) Homepage fetch for link discovery + header hints
    base_final, base_status, base_html, base_headers, base_err = _fetch_html(input_url)
    debug["base_fetch"] = {"final_url": base_final, "status": base_status, "error": base_err, "html_chars": len(base_html)}

    # Sticky heuristics (best-effort)
    sticky_reasons: List[str] = []
    if base_err:
        sticky_reasons.append("fetch_error")
    if base_status in (403, 429, 503):
        sticky_reasons.append(f"http_{base_status}")
    challenge_markers = ("cloudflare", "attention required", "captcha", "perimeterx", "datadome", "access denied")
    if any(m in base_html for m in challenge_markers):
        sticky_reasons.append("bot_protection_challenge")
    # JS-heavy heuristic: very little text, many scripts, or common framework roots.
    if base_html:
        scripts = base_html.count("<script")
        textish = len(re.sub(r"<[^>]+>", " ", base_html))
        if ("id=\"__next\"" in base_html) or ("__next_data__" in base_html) or ("data-reactroot" in base_html):
            sticky_reasons.append("js_framework_root")
        if scripts >= 12 and textish < 5000:
            sticky_reasons.append("js_heavy_minimal_html")

    if sticky_reasons:
        debug["sticky"] = {"is_sticky": True, "reasons": sticky_reasons}

    # Header/cookie hints for Shopify
    set_cookie = base_headers.get("set-cookie", "")
    if "_shopify" in set_cookie or "shopify" in (base_headers.get("server", "") + " " + base_headers.get("x-powered-by", "")):
        model_result = {
            "input_url": input_url,
            "final_platform": "shopify",
            "shop_presence": "shop",
            "other_platform_label": "",
            "confidence": "high",
            "evidence_tier": "A",
            "signals": ["header/cookie:shopify_hint"],
            "reasoning": "HTTP headers/cookies indicate Shopify.",
        }
        return LocalDetectResult(model_result=model_result, debug=debug)

    # 3) Fingerprint homepage
    fp0 = fingerprint_platform(base_final or input_url)
    debug["attempts"].append(
        {
            "url": base_final or input_url,
            "status": base_status,
            "platform": fp0.platform,
            "confidence": fp0.confidence,
            "shop_hint": fp0.shop_presence_hint,
            "signals": fp0.signals,
            "error": fp0.error,
        }
    )

    def _as_model_result(fp_platform: str, signals: List[str], *, shop_presence: str, confidence: str, other_label: str) -> Dict[str, object]:
        return {
            "input_url": input_url,
            "final_platform": fp_platform,
            "shop_presence": shop_presence,
            "other_platform_label": other_label,
            "confidence": confidence,
            "evidence_tier": "A" if confidence in ("high", "medium") else "C",
            "signals": signals[:8],
            "reasoning": "Local HTML fingerprinting.",
        }

    if fp0.platform in ("woocommerce", "shopify", "shopware", "magento"):
        return LocalDetectResult(
            model_result=_as_model_result(fp0.platform, fp0.signals, shop_presence="shop", confidence=fp0.confidence, other_label=""),
            debug=debug,
        )

    # If homepage looks like "other" (e.g. WordPress), do NOT stop here:
    # many businesses host the actual shop on a linked page or shop.<root-domain>.
    # We'll keep a tentative "other" candidate and only return it if shop discovery fails.
    tentative_other = None
    if fp0.platform == "other":
        other_label = "wordpress" if any(s.startswith("wordpress:") for s in fp0.signals) else ""
        # If the homepage itself has strong shop signals, we can accept "other" as a shop-ish site.
        shop_presence = "shop" if fp0.shop_presence_hint == "shop" else "not_shop"
        tentative_other = _as_model_result(
            "other", fp0.signals, shop_presence=shop_presence, confidence=fp0.confidence, other_label=other_label
        )

    # 4) Follow likely shop links on the homepage
    for link in _extract_shop_links(base_final or input_url, base_html):
        fp = fingerprint_platform(link)
        debug["attempts"].append(
            {
                "url": link,
                "platform": fp.platform,
                "confidence": fp.confidence,
                "shop_hint": fp.shop_presence_hint,
                "signals": fp.signals,
                "error": fp.error,
            }
        )
        if fp.platform in ("woocommerce", "shopify", "shopware", "magento"):
            return LocalDetectResult(
                model_result=_as_model_result(fp.platform, fp.signals, shop_presence="shop", confidence=fp.confidence, other_label=""),
                debug=debug,
            )

    # 5) Probe common shop subdomains (shop./store./webshop.)
    for sub_host in _subdomain_candidates(host):
        sub_url = f"https://{sub_host}/"
        fp = fingerprint_platform(sub_url)
        debug["attempts"].append(
            {
                "url": sub_url,
                "platform": fp.platform,
                "confidence": fp.confidence,
                "shop_hint": fp.shop_presence_hint,
                "signals": fp.signals,
                "error": fp.error,
            }
        )
        if fp.platform in ("woocommerce", "shopify", "shopware", "magento"):
            return LocalDetectResult(
                model_result=_as_model_result(fp.platform, fp.signals, shop_presence="shop", confidence=fp.confidence, other_label=""),
                debug=debug,
            )

    if tentative_other is not None:
        return LocalDetectResult(model_result=tentative_other, debug=debug)

    # 6) Give up (unknown)
    model_result = {
        "input_url": input_url,
        "final_platform": "unknown",
        "shop_presence": "unclear",
        "other_platform_label": "",
        "confidence": "low",
        "evidence_tier": "C",
        "signals": [],
        "reasoning": "Local detection inconclusive (JS-heavy site, blocked, or no clear markers).",
    }
    return LocalDetectResult(model_result=model_result, debug=debug)


