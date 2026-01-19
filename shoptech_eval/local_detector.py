from __future__ import annotations

import json
import re
import ssl
import urllib.parse
import urllib.request
import urllib.error
from dataclasses import dataclass
from typing import Dict, List, Tuple

from .dns_probe import probe_shopify_cname
from .fingerprinting import fingerprint_platform, fingerprint_platform_from_html
from .playwright_fetch import fetch_html_playwright


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


def _origin_from_url(url: str) -> str:
    try:
        u = _normalize_url(url)
        pu = urllib.parse.urlparse(u)
        if not pu.scheme or not pu.netloc:
            return ""
        return f"{pu.scheme}://{pu.netloc}"
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


def _probe_shopify_cart_js(host: str, *, timeout_seconds: float = 8.0) -> Tuple[bool, str]:
    """
    Shopify stores typically expose /cart.js returning a JSON cart object.
    This is a strong, cheap "functional shop" signal when reachable.
    Returns (hit, debug_reason).
    """
    h = (host or "").strip().lower().strip(".")
    if not h:
        return False, "empty_host"
    url = f"https://{h}/cart.js"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) shoptech-local-detector/1.0",
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


def _probe_shopware_store_api_context(host: str, *, timeout_seconds: float = 8.0) -> Tuple[bool, str]:
    """
    Shopware 6 storefronts commonly expose the Store API under /store-api/ and require an "sw-access-key" header.

    We intentionally probe /store-api/context without any credentials:
    - If the endpoint exists and returns a JSON error indicating the missing "sw-access-key", that's a strong Shopware signal.
    - Otherwise, we do NOT classify as Shopware from this probe.

    Returns (hit, reason).
    """
    h = (host or "").strip().lower().strip(".")
    if not h:
        return False, "empty_host"
    url = f"https://{h}/store-api/context"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) shoptech-local-detector/1.0",
            "Accept": "application/json,*/*;q=0.8",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=float(timeout_seconds), context=ssl.create_default_context()) as resp:
            status = int(getattr(resp, "status", 0) or 0)
            if status == 200:
                # Even if public, we'd still prefer HTML markers; don't treat 200 as definitive.
                return False, "status_200_no_assert"
            return False, f"status_{status}"
    except urllib.error.HTTPError as e:
        status = int(getattr(e, "code", 0) or 0)
        ct = str(getattr(e, "headers", {}).get("content-type", "") or "").lower()
        try:
            body = (e.read(200_000) or b"").decode("utf-8", errors="replace")
        except Exception:
            body = ""
        if status in (401, 403) and ("json" in ct) and body.strip():
            try:
                obj = json.loads(body)
            except Exception:
                obj = None
            if isinstance(obj, dict) and isinstance(obj.get("errors"), list):
                for err in obj.get("errors") or []:
                    if not isinstance(err, dict):
                        continue
                    detail = str(err.get("detail") or "").lower()
                    if "sw-access-key" in detail:
                        return True, "store_api_requires_sw_access_key"
        return False, f"http_{status}"
    except Exception as e:
        return False, f"{type(e).__name__}:{e}"

def _probe_wc_store_api_products(host: str, *, timeout_seconds: float = 8.0) -> Tuple[bool, str]:
    """
    WooCommerce Store API is commonly exposed at /wp-json/wc/store/products.
    If reachable + returns JSON, it is a strong indication of WooCommerce storefront capability.
    Returns (hit, reason). "hit" means we got a plausible JSON response from the endpoint.
    """
    h = (host or "").strip().lower().strip(".")
    if not h:
        return False, "empty_host"
    url = f"https://{h}/wp-json/wc/store/products?per_page=1"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) shoptech-local-detector/1.0",
            "Accept": "application/json,*/*;q=0.8",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=float(timeout_seconds), context=ssl.create_default_context()) as resp:
            status = int(getattr(resp, "status", 0) or 0)
            body = (resp.read(250_000) or b"").decode("utf-8", errors="replace")
            if status != 200 or not body.strip():
                return False, f"status_{status}"
            try:
                obj = json.loads(body)
            except Exception:
                return False, "json_parse_failed"
            if isinstance(obj, list):
                return True, f"list_len_{len(obj)}"
            if isinstance(obj, dict) and ("products" in obj or "items" in obj):
                return True, "dict_products_like"
            return True, "json_other_shape"
    except Exception as e:
        return False, f"{type(e).__name__}:{e}"


def _extract_shop_links(base_url: str, html: str, *, limit: int = 15) -> List[str]:
    """
    Find likely shop/cart links from a homepage HTML snippet.
    This is intentionally simple and fast (no JS execution).
    """
    if not html:
        return []
    hrefs = re.findall(r"""href\s*=\s*["']([^"']+)["']""", html, flags=re.I)
    keys = (
        # Explicit shop flows
        "shop",
        "store",
        "webshop",
        "onlineshop",
        "online-shop",
        # Cart/checkout words
        "warenkorb",
        "cart",
        "checkout",
        "kasse",
        # Product/order intent
        "produkt",
        "produkte",
        "product",
        "products",
        "kaufen",
        "bestellen",
        # Ticketing/vouchers (still ecommerce-ish)
        "tickets",
        "voucher",
        "gutschein",
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


def detect_platform_local(
    url: str,
    *,
    shop_presence_mode: str = "installed",
    enable_wc_store_api_probe: bool = False,
    cautious_on_sticky: bool = False,
    playwright_fallback_on_blocked: bool = False,
    playwright_fallback_on_unknown: bool = False,
) -> LocalDetectResult:
    """
    API-free local detector:
    - DNS hint for Shopify via CNAME
    - Direct HTML fingerprinting
    - If unclear, follow likely "shop" links and probe common shop subdomains
    """
    # shop_presence_mode semantics:
    # - installed: treat strong platform presence as "shop" even if checkout/cart isn't obvious
    # - functional: require stronger cart/checkout/product evidence before calling it a shop
    mode = (shop_presence_mode or "installed").strip().lower()
    if mode not in ("installed", "functional"):
        mode = "installed"
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
        shop_presence = "shop" if mode == "installed" else "unclear"
        model_result = {
            "input_url": input_url,
            "final_platform": "shopify",
            "shop_presence": shop_presence,
            "other_platform_label": "",
            "confidence": "high",
            "evidence_tier": "A",
            "signals": [f"dns:cname->{dns_hit.shopify_cname}"],
            "reasoning": "DNS CNAME indicates Shopify (myshopify).",
        }
        return LocalDetectResult(model_result=model_result, debug=debug)

    # 1b) Shopify cart.js probe (strong functional signal when reachable)
    if host:
        hit, why = _probe_shopify_cart_js(host)
        debug["shopify_cart_js_probe"] = {"hit": bool(hit), "reason": why}
        if hit:
            model_result = {
                "input_url": input_url,
                "final_platform": "shopify",
                "shop_presence": "shop",
                "other_platform_label": "",
                "confidence": "high",
                "evidence_tier": "A",
                "signals": ["shopify:/cart.js"],
                "reasoning": "Shopify cart endpoint indicates a functional Shopify shop.",
            }
            return LocalDetectResult(model_result=model_result, debug=debug)

    # 1c) Shopware Store API probe (strong installed signal when the endpoint exists).
    if host:
        hit, why = _probe_shopware_store_api_context(host)
        debug["shopware_store_api_probe"] = {"hit": bool(hit), "reason": why}
        if hit:
            shop_presence = "shop" if mode == "installed" else "unclear"
            model_result = {
                "input_url": input_url,
                "final_platform": "shopware",
                "shop_presence": shop_presence,
                "other_platform_label": "",
                "confidence": "high",
                "evidence_tier": "A",
                "signals": ["shopware:/store-api/context", f"shopware:store_api:{why}"],
                "reasoning": "Shopware Store API endpoint indicates Shopware.",
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

    # Optional: Playwright fallback for blocked/inaccessible sites.
    # Only attempt when the normal fetch looks sticky/blocked or errored.
    if playwright_fallback_on_blocked and (not base_html or sticky_reasons):
        pw = fetch_html_playwright(base_final or input_url)
        debug["playwright_fetch"] = {
            "ok": bool(pw.ok),
            "final_url": pw.final_url,
            "status": pw.status,
            "error": pw.error,
            "blocked_reasons": pw.blocked_reasons,
            "html_chars": len(pw.html_lower or ""),
        }
        if pw.ok and pw.html_lower:
            fp_pw = fingerprint_platform_from_html(
                html_lower=pw.html_lower,
                final_url=pw.final_url or (base_final or input_url),
                status=pw.status,
                error="",
                shop_presence_mode=mode,
            )
            debug["attempts"].append(
                {
                    "url": fp_pw.final_url,
                    "status": fp_pw.status,
                    "platform": fp_pw.platform,
                    "confidence": fp_pw.confidence,
                    "shop_hint": fp_pw.shop_presence_hint,
                    "signals": fp_pw.signals,
                    "error": fp_pw.error,
                    "via": "playwright",
                }
            )
            if fp_pw.platform in ("woocommerce", "shopify", "shopware", "magento"):
                sp = "shop" if mode == "installed" else (fp_pw.shop_presence_hint or "unclear")
                return LocalDetectResult(
                    model_result={
                        "input_url": input_url,
                        "final_platform": fp_pw.platform,
                        "shop_presence": sp,
                        "other_platform_label": "",
                        "confidence": fp_pw.confidence,
                        "evidence_tier": "A" if fp_pw.confidence in ("high", "medium") else "C",
                        "signals": fp_pw.signals[:8],
                        "reasoning": "Local HTML fingerprinting (via Playwright fallback).",
                    },
                    debug=debug,
                )

    # Header/cookie hints for Shopware (best-effort)
    header_blob = " ".join(
        [
            base_headers.get("server", ""),
            base_headers.get("x-powered-by", ""),
            base_headers.get("x-generator", ""),
            base_headers.get("set-cookie", ""),
        ]
    ).lower()
    set_cookie = base_headers.get("set-cookie", "")
    sw_cookie_hint = ("sw-context-token" in set_cookie) or ("sw-cache-hash" in set_cookie)
    if any(k.startswith("x-shopware") for k in base_headers.keys()) or ("shopware" in header_blob) or sw_cookie_hint:
        shop_presence = "shop" if mode == "installed" else "unclear"
        model_result = {
            "input_url": input_url,
            "final_platform": "shopware",
            "shop_presence": shop_presence,
            "other_platform_label": "",
            "confidence": "high",
            "evidence_tier": "A",
            "signals": ["header/cookie:shopware_hint"] + (["cookie:sw_context_or_cache_hash"] if sw_cookie_hint else []),
            "reasoning": "HTTP headers/cookies indicate Shopware.",
        }
        return LocalDetectResult(model_result=model_result, debug=debug)

    # Header/cookie hints for Shopify
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
    # Avoid a redundant refetch when we already have base HTML.
    if base_html:
        fp0 = fingerprint_platform_from_html(
            html_lower=base_html,
            final_url=base_final or input_url,
            status=base_status,
            error=base_err,
            shop_presence_mode=mode,
        )
    else:
        fp0 = fingerprint_platform(base_final or input_url, shop_presence_mode=mode)
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
        sp = "shop" if mode == "installed" else (fp0.shop_presence_hint or "unclear")
        return LocalDetectResult(
            model_result=_as_model_result(
                fp0.platform,
                fp0.signals,
                shop_presence=sp,
                confidence=fp0.confidence,
                other_label="",
            ),
            debug=debug,
        )

    # If homepage looks like "other" (e.g. WordPress), do NOT stop here:
    # many businesses host the actual shop on a linked page or shop.<root-domain>.
    # We'll keep a tentative "other" candidate and only return it if shop discovery fails.
    tentative_other = None
    if fp0.platform == "other":
        other_label = "wordpress" if any(s.startswith("wordpress:") for s in fp0.signals) else ""
        # If the homepage itself has strong shop signals, we can accept "other" as a shop-ish site.
        if (
            cautious_on_sticky
            and mode == "functional"
            and bool((debug.get("sticky") or {}).get("is_sticky", False))
        ):
            shop_presence = "unclear"
        else:
            shop_presence = "shop" if fp0.shop_presence_hint == "shop" else "not_shop"
        tentative_other = _as_model_result(
            "other", fp0.signals, shop_presence=shop_presence, confidence=fp0.confidence, other_label=other_label
        )

    # 3b) Optional: if we saw WooCommerce assets but shop presence is unclear/not_shop, probe the Woo Store API.
    # This can improve recall on some sites, but may increase false positives (plugin installed but no obvious checkout).
    if enable_wc_store_api_probe and mode == "functional" and host and any(s.startswith("woocommerce:") for s in fp0.signals):
        hit, why = _probe_wc_store_api_products(host)
        debug["wc_store_api_probe"] = {"hit": bool(hit), "reason": why}
        if hit:
            return LocalDetectResult(
                model_result=_as_model_result(
                    "woocommerce",
                    fp0.signals + [f"woocommerce:store_api:{why}"],
                    shop_presence="shop",
                    confidence="medium",
                    other_label="",
                ),
                debug=debug,
            )

    # 4) Follow likely shop links on the homepage
    for link in _extract_shop_links(base_final or input_url, base_html):
        fp = fingerprint_platform(link, shop_presence_mode=mode)
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
            sp = "shop" if mode == "installed" else (fp.shop_presence_hint or "unclear")
            return LocalDetectResult(
                model_result=_as_model_result(
                    fp.platform,
                    fp.signals,
                    shop_presence=sp,
                    confidence=fp.confidence,
                    other_label="",
                ),
                debug=debug,
            )

    # 4b) Probe a few common shop paths on the same origin (many companies host the storefront at /shop or /store).
    # Keep this intentionally small to avoid slowing down large runs.
    if not sticky_reasons:
        base_origin = _origin_from_url(base_final or input_url)
        if base_origin:
            for path in ("/shop", "/shop/", "/store", "/store/", "/webshop", "/webshop/"):
                candidate = urllib.parse.urljoin(base_origin, path)
                final_u, st, html, _hdrs, err = _fetch_html(candidate, timeout_seconds=10.0, max_bytes=700_000)
                fp = fingerprint_platform_from_html(
                    html_lower=html,
                    final_url=final_u or candidate,
                    status=st,
                    error=err,
                    shop_presence_mode=mode,
                )
                debug["attempts"].append(
                    {
                        "url": final_u or candidate,
                        "status": st,
                        "platform": fp.platform,
                        "confidence": fp.confidence,
                        "shop_hint": fp.shop_presence_hint,
                        "signals": fp.signals,
                        "error": fp.error,
                        "via": "path_probe",
                    }
                )
                if fp.platform in ("woocommerce", "shopify", "shopware", "magento"):
                    sp = "shop" if mode == "installed" else (fp.shop_presence_hint or "unclear")
                    return LocalDetectResult(
                        model_result=_as_model_result(
                            fp.platform,
                            fp.signals,
                            shop_presence=sp,
                            confidence=fp.confidence,
                            other_label="",
                        ),
                        debug=debug,
                    )

    # 5) Probe common shop subdomains (shop./store./webshop.)
    for sub_host in _subdomain_candidates(host):
        sub_url = f"https://{sub_host}/"
        fp = fingerprint_platform(sub_url, shop_presence_mode=mode)
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
            sp = "shop" if mode == "installed" else (fp.shop_presence_hint or "unclear")
            return LocalDetectResult(
                model_result=_as_model_result(
                    fp.platform,
                    fp.signals,
                    shop_presence=sp,
                    confidence=fp.confidence,
                    other_label="",
                ),
                debug=debug,
            )

    if tentative_other is not None:
        return LocalDetectResult(model_result=tentative_other, debug=debug)

    # Optional: Playwright fallback for JS-heavy pages where the plain fetch succeeded but fingerprints were inconclusive.
    # Only attempt when we would otherwise return unknown.
    if playwright_fallback_on_unknown:
        # Avoid double-running if we already did a Playwright fetch above.
        if not isinstance(debug.get("playwright_fetch"), dict):
            pw = fetch_html_playwright(base_final or input_url)
            debug["playwright_fetch"] = {
                "ok": bool(pw.ok),
                "final_url": pw.final_url,
                "status": pw.status,
                "error": pw.error,
                "blocked_reasons": pw.blocked_reasons,
                "html_chars": len(pw.html_lower or ""),
            }
            if pw.ok and pw.html_lower:
                fp_pw = fingerprint_platform_from_html(
                    html_lower=pw.html_lower,
                    final_url=pw.final_url or (base_final or input_url),
                    status=pw.status,
                    error="",
                    shop_presence_mode=mode,
                )
                debug["attempts"].append(
                    {
                        "url": fp_pw.final_url,
                        "status": fp_pw.status,
                        "platform": fp_pw.platform,
                        "confidence": fp_pw.confidence,
                        "shop_hint": fp_pw.shop_presence_hint,
                        "signals": fp_pw.signals,
                        "error": fp_pw.error,
                        "via": "playwright",
                    }
                )
                if fp_pw.platform in ("woocommerce", "shopify", "shopware", "magento"):
                    sp = "shop" if mode == "installed" else (fp_pw.shop_presence_hint or "unclear")
                    model_result = {
                        "input_url": input_url,
                        "final_platform": fp_pw.platform,
                        "shop_presence": sp,
                        "other_platform_label": "",
                        "confidence": fp_pw.confidence,
                        "evidence_tier": "A" if fp_pw.confidence in ("high", "medium") else "C",
                        "signals": fp_pw.signals[:8],
                        "reasoning": "Local HTML fingerprinting (via Playwright fallback).",
                    }
                    return LocalDetectResult(model_result=model_result, debug=debug)

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


