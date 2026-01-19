from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from .shop_functionality import ShopFunctionalityResult
from .playwright_limit import playwright_slot


def _looks_like_bot_challenge(text_lower: str) -> bool:
    t = text_lower or ""
    markers = ("cloudflare", "attention required", "captcha", "perimeterx", "datadome", "access denied")
    return any(m in t for m in markers)


def detect_shop_functionality_playwright(
    url: str,
    *,
    timeout_ms: int = 25_000,
    follow_links: bool = True,
    max_links: int = 4,
) -> ShopFunctionalityResult:
    """
    Headless-browser cart/checkout detector (optional dependency).

    Returns the same presence states as the local HTML checker:
      has_cart_checkout | no_cart_checkout | blocked | error

    Notes:
    - This is best-effort. Some sites will block headless browsers.
    - We keep the checks simple and stable: look for common cart/checkout/product selectors and keywords.
    """
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception as e:
        return ShopFunctionalityResult(
            presence="error",
            signals=["error:missing_playwright"],
            checked_urls=[url],
            error=f"{type(e).__name__}:{e}",
            http_status=None,
            blocked_reasons=[],
        )

    checked: List[str] = []

    def _has_cart_signals(page) -> List[str]:
        sig: List[str] = []
        # Fast keyword checks
        body = (page.content() or "").lower()
        if _looks_like_bot_challenge(body):
            sig.append("blocked:bot_protection_challenge")
            return sig

        # Common Woo/Shopify cart/checkout/product indicators
        selectors = {
            "sel:woocommerce-cart": ".woocommerce-cart, body.woocommerce-cart",
            "sel:woocommerce-checkout": ".woocommerce-checkout, body.woocommerce-checkout",
            "sel:add_to_cart_button": ".add_to_cart_button, [name='add-to-cart'], button[name='add-to-cart']",
            "sel:cart_link": "a[href*='cart'], a[href*='warenkorb'], a[href*='checkout'], a[href*='kasse']",
            "sel:shopify_cart_form": "form[action^='/cart'], a[href^='/cart'], a[href*='/cart']",
        }
        for k, sel in selectors.items():
            try:
                if page.locator(sel).first.count() > 0:
                    sig.append(k)
            except Exception:
                continue

        # Text hints (German/English)
        for w in ("warenkorb", "checkout", "kasse", "add to cart", "in den warenkorb"):
            if w in body:
                sig.append(f"text:{w}")

        return list(dict.fromkeys(sig))

    with playwright_slot():
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()
            try:
                resp = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                status = int(resp.status) if resp is not None else None
                checked.append(page.url)
                # Hard blocks
                content = (page.content() or "").lower()
                if status in (403, 429, 503) or _looks_like_bot_challenge(content):
                    reasons = []
                    if status in (403, 429, 503):
                        reasons.append(f"http_{status}")
                    if _looks_like_bot_challenge(content):
                        reasons.append("bot_protection_challenge")
                    return ShopFunctionalityResult(
                        presence="blocked",
                        signals=[f"blocked:{r}" for r in reasons] or ["blocked"],
                        checked_urls=checked,
                        error="",
                        http_status=status,
                        blocked_reasons=reasons,
                    )

                sig = _has_cart_signals(page)
                if any(s.startswith("blocked:") for s in sig):
                    return ShopFunctionalityResult(
                        presence="blocked",
                        signals=sig,
                        checked_urls=checked,
                        error="",
                        http_status=status,
                        blocked_reasons=[s.split(":", 1)[1] for s in sig if s.startswith("blocked:")],
                    )
                if sig:
                    return ShopFunctionalityResult(
                        presence="has_cart_checkout",
                        signals=sig,
                        checked_urls=checked,
                        error="",
                        http_status=status,
                        blocked_reasons=[],
                    )

                if follow_links:
                    # Follow a few likely links to shop/cart/checkout pages.
                    link_selectors = [
                        "a[href*='shop']",
                        "a[href*='store']",
                        "a[href*='webshop']",
                        "a[href*='cart']",
                        "a[href*='warenkorb']",
                        "a[href*='checkout']",
                        "a[href*='kasse']",
                        "a[href*='produkte']",
                        "a[href*='product']",
                    ]
                    seen = set()
                    links = []
                    for sel in link_selectors:
                        try:
                            for el in page.locator(sel).all()[: max_links]:
                                href = el.get_attribute("href") or ""
                                if href and href not in seen:
                                    seen.add(href)
                                    links.append(href)
                        except Exception:
                            continue
                        if len(links) >= max_links:
                            break

                    for href in links[:max_links]:
                        try:
                            page.goto(href, wait_until="domcontentloaded", timeout=timeout_ms)
                            checked.append(page.url)
                            sig2 = _has_cart_signals(page)
                            if sig2:
                                return ShopFunctionalityResult(
                                    presence="has_cart_checkout",
                                    signals=sig2 + ["via_link"],
                                    checked_urls=checked,
                                    error="",
                                    http_status=None,
                                    blocked_reasons=[],
                                )
                        except Exception:
                            continue

                return ShopFunctionalityResult(
                    presence="no_cart_checkout",
                    signals=[],
                    checked_urls=checked,
                    error="",
                    http_status=status,
                    blocked_reasons=[],
                )
            except Exception as e:
                return ShopFunctionalityResult(
                    presence="error",
                    signals=["error:playwright_exception"],
                    checked_urls=checked or [url],
                    error=f"{type(e).__name__}:{e}",
                    http_status=None,
                    blocked_reasons=[],
                )
            finally:
                try:
                    context.close()
                except Exception:
                    pass
                try:
                    browser.close()
                except Exception:
                    pass

