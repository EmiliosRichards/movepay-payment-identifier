from __future__ import annotations

import re
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class FingerprintResult:
    platform: str  # magento|shopware|woocommerce|shopify|other|unknown|inconclusive|error
    confidence: str  # low|medium|high
    signals: List[str]
    shop_presence_hint: str  # shop|not_shop|unclear
    final_url: str
    status: Optional[int]
    error: str


def _normalize_url(url: str) -> str:
    u = (url or "").strip()
    if not u:
        return ""
    if not u.lower().startswith(("http://", "https://")):
        u = "https://" + u
    return u


def _fetch_html(url: str, *, timeout_seconds: float = 12.0, max_bytes: int = 600_000) -> Tuple[str, str, Optional[int], str]:
    """Return (final_url, html_text_lower, status_code, error_str)."""
    u = _normalize_url(url)
    if not u:
        return "", "", None, "empty_url"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) shoptech-fingerprint/1.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.8,de-DE,de;q=0.6",
    }
    req = urllib.request.Request(u, headers=headers, method="GET")

    ctx = ssl.create_default_context()
    ctx.check_hostname = True

    try:
        with urllib.request.urlopen(req, timeout=float(timeout_seconds), context=ctx) as resp:
            final_url = getattr(resp, "geturl", lambda: u)() or u
            status = getattr(resp, "status", None)
            raw = resp.read(int(max_bytes) if max_bytes else 0) or b""
            # Best-effort decode
            try:
                text = raw.decode("utf-8", errors="replace")
            except Exception:
                text = raw.decode("latin-1", errors="replace")
            return final_url, text.lower(), int(status) if status is not None else None, ""
    except urllib.error.HTTPError as e:
        # HTTPError is also a response; keep code and any body snippet.
        try:
            raw = e.read(int(max_bytes)) or b""
            txt = raw.decode("utf-8", errors="replace").lower()
        except Exception:
            txt = ""
        return u, txt, int(getattr(e, "code", 0) or 0) or None, f"HTTPError:{getattr(e, 'code', '')}"
    except Exception as e:
        return u, "", None, f"{type(e).__name__}:{e}"


def fingerprint_platform(url: str) -> FingerprintResult:
    """
    A lightweight, independent verifier that looks for strong platform markers in fetched HTML.

    Notes:
    - This is best-effort and may be blocked by bot protections or require JS rendering.
    - When markers are absent, we return inconclusive rather than guessing.
    """
    final_url, html, status, err = _fetch_html(url)
    if err and not html:
        return FingerprintResult(
            platform="error",
            confidence="low",
            signals=[],
            shop_presence_hint="unclear",
            final_url=final_url,
            status=status,
            error=err,
        )

    signals: List[str] = []

    def has(s: str) -> bool:
        return s in html

    # Shop presence heuristic (best-effort; JS-heavy sites may not expose these in initial HTML)
    shop_markers = 0
    for s in (
        "add-to-cart",
        "woocommerce-cart",
        "woocommerce-checkout",
        "?add-to-cart=",
        "/cart",
        "/checkout",
        "warenkorb",
        "kasse",
        "checkout",
    ):
        if has(s):
            shop_markers += 1
    if '"@type":"product"' in html or '"@type": "product"' in html:
        shop_markers += 1
        signals.append("hint:jsonld_product")

    shop_hint = "unclear"
    if shop_markers >= 2:
        shop_hint = "shop"
    elif shop_markers == 0:
        shop_hint = "not_shop"

    # Shopify (strong markers)
    shopify_hits = 0
    for s in ("cdn.shopify.com", "myshopify.com", "shopify-section", "shopify.theme", "shopifyanalytics"):
        if has(s):
            signals.append(f"shopify:{s}")
            shopify_hits += 1
    if shopify_hits >= 1:
        return FingerprintResult("shopify", "high", signals, shop_hint, final_url, status, err)

    # WooCommerce / WordPress
    wc_hits = 0
    for s in ("wp-content/plugins/woocommerce", "woocommerce_params", "wc-cart-fragments", "woocommerce_items_in_cart"):
        if has(s):
            signals.append(f"woocommerce:{s}")
            wc_hits += 1
    # Important: WooCommerce assets can appear even on non-shops (plugin installed but not used).
    # Require at least some shop presence markers before declaring WooCommerce confidently.
    if wc_hits >= 1 and shop_hint == "shop":
        return FingerprintResult("woocommerce", "high", signals, shop_hint, final_url, status, err)
    if wc_hits >= 1 and shop_hint != "shop":
        signals.append("hint:woocommerce_assets_without_shop_signals")

    # Shopware 6 storefront
    sw_hits = 0
    for s in ("/bundles/storefront", "shopware"):
        if has(s):
            signals.append(f"shopware:{s}")
            sw_hits += 1
    # Require the storefront bundle path to avoid false positives from generic "shopware" mentions.
    if has("/bundles/storefront"):
        return FingerprintResult("shopware", "high", signals, shop_hint, final_url, status, err)

    # Magento / Adobe Commerce (use only stronger markers to avoid false positives)
    mag_hits = 0
    for s in ("magento_", "form_key", "/static/frontend/", "/rest/v1/", "/rest/v1/"):
        if has(s):
            signals.append(f"magento:{s}")
            mag_hits += 1
    if mag_hits >= 1 and (has("magento_") or has("form_key") or has("/rest/v1/") or has("/static/frontend/")):
        return FingerprintResult("magento", "high", signals, shop_hint, final_url, status, err)

    # WordPress without WooCommerce is useful for "other_platform_label=wordpress" cases.
    wp_hits = 0
    for s in ("wp-content/", "wp-includes/", "wp-json/"):
        if has(s):
            wp_hits += 1
    if wp_hits >= 2:
        signals.append("wordpress:wp-content/wp-includes/wp-json")
        return FingerprintResult("other", "medium", signals, shop_hint, final_url, status, err)

    # If we got a page but can't identify, mark inconclusive.
    if html:
        # Very weak ecommerce heuristic: presence of cart/checkout strings
        if re.search(r"\b(cart|checkout|warenkorb|kasse)\b", html):
            signals.append("hint:cart/checkout_words_present")
        return FingerprintResult("inconclusive", "low", signals, shop_hint, final_url, status, err)

    return FingerprintResult("inconclusive", "low", [], shop_hint, final_url, status, err)


