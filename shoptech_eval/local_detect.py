from __future__ import annotations

import re
import socket
import ssl
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .fingerprinting import FingerprintResult, fingerprint_platform


@dataclass(frozen=True)
class LocalDetectConfig:
    timeout_seconds: float = 10.0
    max_bytes: int = 700_000
    max_candidates: int = 8
    probe_shop_subdomains: bool = True
    probe_shop_links: bool = True
    enable_dns_shopify: bool = True


def _normalize_url(url: str) -> str:
    u = (url or "").strip()
    if not u:
        return ""
    if not u.lower().startswith(("http://", "https://")):
        u = "https://" + u
    return u


def _hostname_from_url(url: str) -> str:
    try:
        pu = urllib.parse.urlparse(_normalize_url(url))
        return (pu.hostname or "").strip().lower()
    except Exception:
        return ""


def _registered_domain(host: str) -> str:
    """Best-effort registered domain extraction (good enough for .de/.com/.net)."""
    h = (host or "").strip().lower().rstrip(".")
    parts = [p for p in h.split(".") if p]
    if len(parts) <= 2:
        return h
    # Naive: last 2 labels.
    return ".".join(parts[-2:])


def _same_reg_domain(a_host: str, b_host: str) -> bool:
    ra = _registered_domain(a_host)
    rb = _registered_domain(b_host)
    return bool(ra) and ra == rb


def _fetch_html_and_headers(url: str, *, timeout_seconds: float, max_bytes: int) -> Tuple[str, str, Dict[str, str], Optional[int], str]:
    """Return (final_url, html_lower, headers_lower_map, status, error)."""
    u = _normalize_url(url)
    if not u:
        return "", "", {}, None, "empty_url"
    req = urllib.request.Request(
        u,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) shoptech-local-detect/1.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.8,de-DE,de;q=0.6",
        },
        method="GET",
    )
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=float(timeout_seconds), context=ctx) as resp:
            final = resp.geturl() or u
            status = getattr(resp, "status", None)
            raw = resp.read(int(max_bytes) if max_bytes else 0) or b""
            txt = raw.decode("utf-8", errors="replace").lower()
            headers = {}
            try:
                for k, v in (resp.headers.items() if hasattr(resp, "headers") else []):
                    if k and v:
                        headers[str(k).lower()] = str(v).lower()
            except Exception:
                headers = {}
            return final, txt, headers, int(status) if status is not None else None, ""
    except Exception as e:
        return u, "", {}, None, f"{type(e).__name__}:{e}"


def _extract_candidate_links(html: str, base_url: str) -> List[str]:
    hrefs = re.findall(r"""href\s*=\s*["']([^"']+)["']""", html or "", flags=re.I)
    keywords = (
        "shop",
        "store",
        "warenkorb",
        "cart",
        "checkout",
        "kasse",
        "tickets",
        "ticket",
    )
    out: List[str] = []
    for href in hrefs:
        if not href:
            continue
        low = href.lower()
        if any(k in low for k in keywords):
            u = urllib.parse.urljoin(base_url, href)
            if u not in out:
                out.append(u)
    return out


def _probe_shop_subdomain_urls(host: str) -> List[str]:
    reg = _registered_domain(host)
    if not reg or reg.count(".") < 1:
        return []
    # Common shop subdomains.
    return [f"https://shop.{reg}/", f"https://store.{reg}/"]


def _detect_shopify_via_dns(host: str) -> List[str]:
    """Return signals if DNS suggests Shopify (requires dnspython if available; otherwise returns empty)."""
    signals: List[str] = []
    try:
        import dns.resolver  # type: ignore

        # Try www + apex
        candidates = []
        reg = _registered_domain(host)
        if reg:
            candidates.append(reg)
            candidates.append("www." + reg)
        else:
            candidates.append(host)

        for h in candidates:
            try:
                # CNAME check
                ans = dns.resolver.resolve(h, "CNAME")
                for rdata in ans:
                    target = str(rdata.target).rstrip(".").lower()
                    if "myshopify.com" in target or "shops.myshopify.com" in target:
                        signals.append(f"dns:shopify_cname:{h}")
                        return signals
            except Exception:
                pass
    except Exception:
        return []
    return signals


def local_detect(url: str, *, cfg: LocalDetectConfig | None = None) -> Dict[str, Any]:
    """
    API-free detection:
    - HTML fingerprinting (direct markers)
    - Lightweight crawl for shop links
    - Shop subdomain probing (shop./store.)
    - DNS CNAME hinting for Shopify (optional)
    """
    cfg = cfg or LocalDetectConfig()
    input_url = _normalize_url(url)
    host = _hostname_from_url(input_url)

    signals: List[str] = ["detector:local"]

    # DNS hinting (Shopify)
    if cfg.enable_dns_shopify and host:
        dns_signals = _detect_shopify_via_dns(host)
        signals.extend(dns_signals[:2])

    # Fingerprint the provided URL first
    fp_primary = fingerprint_platform(input_url)

    candidates: List[Tuple[str, FingerprintResult]] = [(input_url, fp_primary)]

    # Fetch homepage (for link extraction) using final URL if possible
    final_url, html, _headers, _status, _err = _fetch_html_and_headers(input_url, timeout_seconds=cfg.timeout_seconds, max_bytes=cfg.max_bytes)
    if cfg.probe_shop_links and html and final_url:
        for link in _extract_candidate_links(html, final_url)[: cfg.max_candidates]:
            link_host = _hostname_from_url(link)
            if host and link_host and not _same_reg_domain(host, link_host):
                continue
            candidates.append((link, fingerprint_platform(link)))

    if cfg.probe_shop_subdomains and host:
        for sub in _probe_shop_subdomain_urls(host):
            candidates.append((sub, fingerprint_platform(sub)))

    # Choose best candidate by a simple score
    def score(fp: FingerprintResult) -> int:
        base = 0
        if fp.platform in ("shopify", "woocommerce", "shopware", "magento") and fp.confidence == "high":
            base = 100
        elif fp.platform == "other" and fp.confidence in ("medium", "high"):
            base = 60
        elif fp.platform == "inconclusive":
            base = 10
        elif fp.platform == "error":
            base = 0
        if fp.shop_presence_hint == "shop":
            base += 10
        return base

    best_url, best_fp = max(candidates, key=lambda kv: score(kv[1]))

    # Platform decision
    final_platform = best_fp.platform
    other_label = ""
    if final_platform not in ("magento", "shopware", "woocommerce", "shopify", "other", "unknown"):
        final_platform = "unknown"
    if final_platform == "other":
        # If we saw WordPress markers, label it.
        if any(s.startswith("wordpress:") for s in best_fp.signals):
            other_label = "wordpress"

    # Shopify via DNS if HTML couldn’t confirm but DNS did
    if final_platform == "unknown" and any(s.startswith("dns:shopify_cname") for s in signals):
        final_platform = "shopify"
        best_fp = FingerprintResult(
            platform="shopify",
            confidence="medium",
            signals=[*best_fp.signals, "shopify:dns_cname_hint"],
            shop_presence_hint="unclear",
            final_url=best_fp.final_url,
            status=best_fp.status,
            error=best_fp.error,
        )

    # Presence: use hint, but if platform is a known ecommerce platform, treat as shop (lead intent) unless clearly not_shop.
    shop_presence = best_fp.shop_presence_hint
    if final_platform in ("shopify", "woocommerce", "shopware", "magento") and shop_presence == "unclear":
        shop_presence = "shop"

    confidence = "low"
    evidence_tier = "C"
    if final_platform in ("shopify", "woocommerce", "shopware", "magento") and best_fp.confidence == "high":
        confidence = "high"
        evidence_tier = "A"
    elif final_platform == "other":
        confidence = "medium"
        evidence_tier = "A" if any(s.startswith("wordpress:") for s in best_fp.signals) else "B"
    elif final_platform == "shopify" and any(s.startswith("dns:shopify_cname") for s in signals):
        confidence = "medium"
        evidence_tier = "A"

    # Merge signals
    merged_signals = []
    merged_signals.extend(signals)
    merged_signals.extend(best_fp.signals)
    if best_url != input_url:
        merged_signals.append("hint:shop_found_via_link_or_subdomain")
    merged_signals = merged_signals[:8]

    reasoning_bits = []
    if final_platform in ("shopify", "woocommerce", "shopware", "magento"):
        reasoning_bits.append(f"Local HTML/DNS checks indicate {final_platform}.")
    elif final_platform == "other":
        reasoning_bits.append("Local checks indicate a non-listed platform (likely WordPress).")
    else:
        reasoning_bits.append("Local checks were inconclusive.")
    if any(s.startswith("woocommerce:") for s in best_fp.signals):
        reasoning_bits.append("WooCommerce markers were present in page assets/scripts.")
    if any(s.startswith("shopify:") for s in best_fp.signals) or any(s.startswith("dns:shopify_cname") for s in signals):
        reasoning_bits.append("Shopify markers were present in assets or DNS.")
    if shop_presence == "shop":
        reasoning_bits.append("Site shows shop/cart/checkout indicators.")
    elif shop_presence == "not_shop":
        reasoning_bits.append("No shop/cart/checkout indicators found.")

    reasoning = " ".join(reasoning_bits)
    if len(reasoning) > 600:
        reasoning = reasoning[:597] + "..."

    return {
        "input_url": input_url,
        "shop_presence": shop_presence,
        "final_platform": final_platform,
        "other_platform_label": other_label,
        "confidence": confidence,
        "evidence_tier": evidence_tier,
        "signals": merged_signals,
        "reasoning": reasoning,
    }


