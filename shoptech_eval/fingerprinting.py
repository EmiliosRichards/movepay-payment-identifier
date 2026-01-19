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


def fingerprint_platform_from_html(
    *,
    html_lower: str,
    final_url: str,
    status: Optional[int],
    error: str,
    shop_presence_mode: str = "installed",
) -> FingerprintResult:
    """
    Same fingerprinting logic as fingerprint_platform(), but runs on already-fetched HTML.
    Useful for Playwright-based fetch/render fallbacks.
    """
    mode = (shop_presence_mode or "installed").strip().lower()
    if mode not in ("installed", "functional"):
        mode = "installed"

    html = (html_lower or "").lower()
    signals: List[str] = []

    def has(s: str) -> bool:
        return s in html

    # Shop presence heuristic (best-effort; JS-heavy sites may not expose these in initial HTML)
    # We separate "strong" vs "weak" indicators so we can tighten behavior when desired.
    strong_hits: List[str] = []
    weak_hits: List[str] = []

    # Strong indicators: typically imply real ecommerce *product* behavior (more than just navigation/cart template).
    for s in (
        "?add-to-cart=",
        "add_to_cart_button",
        "data-product_id",
    ):
        if has(s):
            strong_hits.append(s)
    if '"@type":"product"' in html or '"@type": "product"' in html:
        strong_hits.append("jsonld_product")
        signals.append("hint:jsonld_product")

    # Weak indicators: may appear on brochure sites or templates even without functional checkout.
    # (We include common cart/checkout words and WooCommerce template classes here.)
    for s in ("/cart", "/checkout", "warenkorb", "kasse", "checkout", "woocommerce-cart", "woocommerce-checkout", "wc-cart-fragments"):
        if has(s):
            weak_hits.append(s)

    shop_hint = "unclear"
    if mode == "functional":
        if strong_hits:
            shop_hint = "shop"
        elif not weak_hits:
            shop_hint = "not_shop"
        else:
            shop_hint = "unclear"
    else:
        if strong_hits or len(weak_hits) >= 2:
            shop_hint = "shop"
        elif not weak_hits:
            shop_hint = "not_shop"
        else:
            shop_hint = "unclear"

    if shop_hint == "shop" and (not strong_hits) and weak_hits:
        signals.append("hint:shop_presence_weak_only")

    # Shopify (strong markers)
    shopify_hits = 0
    for s in ("cdn.shopify.com", "myshopify.com", "shopify-section", "shopify.theme", "shopifyanalytics"):
        if has(s):
            signals.append(f"shopify:{s}")
            shopify_hits += 1
    if shopify_hits >= 1:
        return FingerprintResult("shopify", "high", signals, shop_hint, final_url, status, error)

    # WooCommerce / WordPress
    wc_hits = 0
    for s in ("wp-content/plugins/woocommerce", "woocommerce_params", "wc-cart-fragments", "woocommerce_items_in_cart"):
        if has(s):
            signals.append(f"woocommerce:{s}")
            wc_hits += 1
    if wc_hits >= 1 and shop_hint == "shop":
        return FingerprintResult("woocommerce", "high", signals, shop_hint, final_url, status, error)
    if wc_hits >= 1 and shop_hint != "shop":
        signals.append("hint:woocommerce_assets_without_shop_signals")

    # Shopware (strong markers)
    # Shopware 6 commonly exposes "/bundles/storefront" assets on the storefront.
    for s in ("/bundles/storefront",):
        if has(s):
            signals.append(f"shopware:{s}")
            return FingerprintResult("shopware", "high", signals, shop_hint, final_url, status, error)

    # Shopware 6 often exposes plugin metadata in HTML (very distinctive).
    # Example: data-plugin-version="shopware6_1.5.0"
    if 'data-plugin-version="shopware' in html or "data-plugin-version='shopware" in html:
        signals.append("shopware:data-plugin-version")
        return FingerprintResult("shopware", "high", signals, shop_hint, final_url, status, error)
    if "window.shopware" in html:
        signals.append("shopware:window.shopware")
        return FingerprintResult("shopware", "high", signals, shop_hint, final_url, status, error)

    # Meta generator tags sometimes expose Shopware directly.
    if re.search(r'<meta[^>]+name=["\']generator["\'][^>]+content=["\'][^"\']*shopware', html):
        signals.append("shopware:meta_generator")
        return FingerprintResult("shopware", "high", signals, shop_hint, final_url, status, error)

    # Shopware 5 often exposes "/themes/Frontend" assets and/or "shopware.php" front controller URLs.
    # (We keep these lowercase because html is lowercased above.)
    for s in ("shopware.php", "/themes/frontend", "jquery.shopware", "/engine/shopware", "shopware.apps"):
        if has(s):
            signals.append(f"shopware:{s}")
            return FingerprintResult("shopware", "high", signals, shop_hint, final_url, status, error)

    # Weak/auxiliary hints (do not classify on their own)
    if has("/widgets/"):
        signals.append("shopware:widgets_path")
    if has("shopware"):
        signals.append("shopware:shopware_word")

    # Magento / Adobe Commerce
    for s in ("magento_", "form_key", "/static/frontend/", "/rest/v1/", "/rest/v1/"):
        if has(s):
            signals.append(f"magento:{s}")
            return FingerprintResult("magento", "high", signals, shop_hint, final_url, status, error)

    # WordPress without WooCommerce
    wp_hits = 0
    for s in ("wp-content/", "wp-includes/", "wp-json/"):
        if has(s):
            wp_hits += 1
    if wp_hits >= 2:
        signals.append("wordpress:wp-content/wp-includes/wp-json")
        return FingerprintResult("other", "medium", signals, shop_hint, final_url, status, error)

    if html:
        if re.search(r"\b(cart|checkout|warenkorb|kasse)\b", html):
            signals.append("hint:cart/checkout_words_present")
        return FingerprintResult("inconclusive", "low", signals, shop_hint, final_url, status, error)

    return FingerprintResult("inconclusive", "low", [], shop_hint, final_url, status, error)


def fingerprint_platform(url: str, *, shop_presence_mode: str = "installed") -> FingerprintResult:
    """
    A lightweight, independent verifier that looks for strong platform markers in fetched HTML.

    Notes:
    - This is best-effort and may be blocked by bot protections or require JS rendering.
    - When markers are absent, we return inconclusive rather than guessing.
    """
    mode = (shop_presence_mode or "installed").strip().lower()
    if mode not in ("installed", "functional"):
        mode = "installed"
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
    return fingerprint_platform_from_html(
        html_lower=html,
        final_url=final_url,
        status=status,
        error=err,
        shop_presence_mode=mode,
    )


