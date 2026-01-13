from __future__ import annotations

import json
import re
import ssl
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Dict, List, Tuple


@dataclass(frozen=True)
class ShopFunctionalityResult:
    presence: str  # has_cart_checkout|no_cart_checkout|blocked|error
    signals: List[str]
    checked_urls: List[str]
    error: str
    http_status: int | None = None
    blocked_reasons: List[str] = field(default_factory=list)


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


def _fetch(url: str, *, timeout_seconds: float, max_bytes: int) -> Tuple[str, int | None, str, Dict[str, str], str]:
    """Return (final_url, status_code, body_lower, headers_lower, error_str)."""
    u = _normalize_url(url)
    if not u:
        return "", None, "", {}, "empty_url"
    req = urllib.request.Request(
        u,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) shoptech-functional-check/1.0",
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


def _extract_candidate_links(base_url: str, html: str, *, limit: int = 8) -> List[str]:
    if not html:
        return []
    hrefs = re.findall(r"""href\s*=\s*["']([^"']+)["']""", html, flags=re.I)
    keys = (
        "shop",
        "store",
        "webshop",
        "onlineshop",
        "online-shop",
        "warenkorb",
        "cart",
        "checkout",
        "kasse",
        "product",
        "products",
        "produkt",
        "produkte",
        "kaufen",
        "bestellen",
    )
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


def _is_sticky(status: int | None, html: str, err: str) -> Tuple[bool, List[str]]:
    reasons: List[str] = []
    if err:
        reasons.append("fetch_error")
    if status in (403, 429, 503):
        reasons.append(f"http_{status}")
    markers = ("cloudflare", "attention required", "captcha", "perimeterx", "datadome", "access denied")
    if any(m in (html or "") for m in markers):
        reasons.append("bot_protection_challenge")
    return (len(reasons) > 0), reasons


def _shop_signals_from_html(html: str, headers: Dict[str, str]) -> List[str]:
    h = html or ""
    sig: List[str] = []

    # Strong cart/checkout/product behavior signals
    strong = (
        "woocommerce-cart",
        "woocommerce-checkout",
        "woocommerce_items_in_cart",
        "wc-cart-fragments",
        "?add-to-cart=",
        "add_to_cart_button",
        "data-product_id",
    )
    for s in strong:
        if s in h:
            sig.append(f"html:{s}")

    if '"@type":"product"' in h or '"@type": "product"' in h:
        sig.append("html:jsonld_product")

    # Shopify hints (cart.js is handled separately; here we note html/header hints)
    if "cdn.shopify.com" in h or "myshopify.com" in h:
        sig.append("html:shopify_asset")
    set_cookie = (headers or {}).get("set-cookie", "")
    if "_shopify" in set_cookie:
        sig.append("header:_shopify_cookie")

    return sig


def _probe_shopify_cart_js(host: str, *, timeout_seconds: float = 8.0) -> Tuple[bool, str]:
    h = (host or "").strip().lower().strip(".")
    if not h:
        return False, "empty_host"
    url = f"https://{h}/cart.js"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) shoptech-functional-check/1.0",
            "Accept": "application/json,text/javascript,*/*;q=0.8",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=float(timeout_seconds), context=ssl.create_default_context()) as resp:
            status = int(getattr(resp, "status", 0) or 0)
            body = (resp.read(200_000) or b"").decode("utf-8", errors="replace")
            if status != 200 or not body.strip():
                return False, f"status_{status}"
            try:
                obj = json.loads(body)
            except Exception:
                return False, "json_parse_failed"
            if isinstance(obj, dict) and "items" in obj:
                return True, "cart_js_items"
            return False, "json_no_items"
    except Exception as e:
        return False, f"{type(e).__name__}:{e}"


def detect_shop_functionality(
    url: str,
    *,
    timeout_seconds: float = 12.0,
    max_bytes: int = 400_000,
    follow_links: bool = True,
    link_limit: int = 6,
) -> ShopFunctionalityResult:
    """
    Best-effort, API-free check: does the site expose cart/checkout-style functionality?

    It is intentionally conservative:
    - returns has_cart_checkout only with strong evidence
    - returns unclear for sticky/blocked/JS-challenge pages
    """
    input_url = _normalize_url(url)
    host = _host_from_url(input_url)
    checked: List[str] = []

    # Shopify /cart.js probe is a cheap strong signal (when reachable).
    if host:
        hit, why = _probe_shopify_cart_js(host, timeout_seconds=min(8.0, float(timeout_seconds)))
        if hit:
            return ShopFunctionalityResult(
                presence="has_cart_checkout",
                signals=[f"shopify:/cart.js:{why}"],
                checked_urls=[f"https://{host}/cart.js"],
                error="",
                http_status=200,
                blocked_reasons=[],
            )

    final_url, status, html, headers, err = _fetch(input_url, timeout_seconds=float(timeout_seconds), max_bytes=int(max_bytes))
    checked.append(final_url or input_url)

    sticky, sticky_reasons = _is_sticky(status, html, err)
    sig = _shop_signals_from_html(html, headers)
    # Hard failure
    if err and not html:
        return ShopFunctionalityResult(
            presence="error",
            signals=["error:fetch_failed"],
            checked_urls=checked,
            error=err,
            http_status=status,
            blocked_reasons=[],
        )
    if sticky:
        # We still might have gotten enough evidence in HTML despite a challenge banner; if so, allow has_cart_checkout.
        if any(s.startswith("html:") for s in sig):
            return ShopFunctionalityResult("has_cart_checkout", sig + [f"sticky:{r}" for r in sticky_reasons], checked, "")
        return ShopFunctionalityResult(
            "blocked",
            [f"blocked:{r}" for r in sticky_reasons],
            checked,
            err,
            http_status=status,
            blocked_reasons=sticky_reasons,
        )

    # Strong evidence found on the main page.
    if any(s.startswith("html:") for s in sig) or any(s.startswith("shopify:/cart.js") for s in sig):
        return ShopFunctionalityResult("has_cart_checkout", sig, checked, "", http_status=status, blocked_reasons=[])

    # Optional: follow candidate links (shop/cart/checkout/product pages).
    if follow_links and html:
        for link in _extract_candidate_links(final_url or input_url, html, limit=int(link_limit)):
            f2, st2, h2, hdr2, e2 = _fetch(link, timeout_seconds=float(timeout_seconds), max_bytes=int(max_bytes))
            checked.append(f2 or link)
            sticky2, reasons2 = _is_sticky(st2, h2, e2)
            sig2 = _shop_signals_from_html(h2, hdr2)
            if any(s.startswith("html:") for s in sig2):
                return ShopFunctionalityResult(
                    "has_cart_checkout",
                    sig2 + ["via_link"],
                    checked,
                    "",
                    http_status=st2,
                    blocked_reasons=[],
                )
            if sticky2:
                # Don't mark as no_cart if the likely shop page is blocked.
                return ShopFunctionalityResult(
                    "blocked",
                    [f"blocked:{r}" for r in reasons2] + ["via_link"],
                    checked,
                    e2,
                    http_status=st2,
                    blocked_reasons=reasons2,
                )

    # No strong cart/checkout evidence observed.
    return ShopFunctionalityResult("no_cart_checkout", sig, checked, err, http_status=status, blocked_reasons=[])

