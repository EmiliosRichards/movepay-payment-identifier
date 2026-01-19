from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from .playwright_limit import playwright_slot


@dataclass(frozen=True)
class PlaywrightFetchResult:
    ok: bool
    final_url: str
    status: int | None
    html_lower: str
    error: str
    blocked_reasons: List[str]


def _looks_like_bot_challenge(text_lower: str) -> bool:
    t = text_lower or ""
    markers = ("cloudflare", "attention required", "captcha", "perimeterx", "datadome", "access denied")
    return any(m in t for m in markers)


def fetch_html_playwright(url: str, *, timeout_ms: int = 25_000) -> PlaywrightFetchResult:
    """
    Best-effort HTML fetch using a headless browser (optional dependency).

    - If Playwright isn't installed, returns ok=False with error=missing_playwright.
    - If the site blocks headless or returns a challenge page, returns ok=False with blocked_reasons.
    """
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception as e:
        return PlaywrightFetchResult(
            ok=False,
            final_url=url,
            status=None,
            html_lower="",
            error=f"missing_playwright:{type(e).__name__}:{e}",
            blocked_reasons=[],
        )

    blocked: List[str] = []
    final_url = url
    status: int | None = None
    html_lower = ""
    err = ""

    with playwright_slot():
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()
            try:
                resp = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                final_url = page.url or url
                status = int(resp.status) if resp is not None else None
                html_lower = (page.content() or "").lower()

                if status in (403, 429, 503):
                    blocked.append(f"http_{status}")
                if _looks_like_bot_challenge(html_lower):
                    blocked.append("bot_protection_challenge")

                if blocked:
                    return PlaywrightFetchResult(
                        ok=False,
                        final_url=final_url,
                        status=status,
                        html_lower=html_lower,
                        error="blocked",
                        blocked_reasons=blocked,
                    )

                if not html_lower.strip():
                    return PlaywrightFetchResult(
                        ok=False,
                        final_url=final_url,
                        status=status,
                        html_lower="",
                        error="empty_html",
                        blocked_reasons=[],
                    )

                return PlaywrightFetchResult(
                    ok=True,
                    final_url=final_url,
                    status=status,
                    html_lower=html_lower,
                    error="",
                    blocked_reasons=[],
                )
            except Exception as e:
                err = f"{type(e).__name__}:{e}"
                return PlaywrightFetchResult(
                    ok=False,
                    final_url=final_url,
                    status=status,
                    html_lower=html_lower,
                    error=err,
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

