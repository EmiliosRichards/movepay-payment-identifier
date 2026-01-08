## Goal

Detect which **ecommerce platform** a shop uses for the provided domain.

Your output must choose exactly one:
- **magento**
- **shopware**
- **woocommerce**
- **shopify**
- **other**
- **unknown**

You must also output:
- `shop_presence`: shop|not_shop|unclear
- `confidence`: low|medium|high
- `evidence_tier`: A|B|C
- `signals`: short bullet-like strings (max 8) describing the strongest platform indicators found
- `other_platform_label`: short known label when `final_platform=other` (else empty string)
- `reasoning`: 2–4 sentences, ≤600 characters, **no raw URLs**

---

## Evidence tiers (A/B/C)

### Tier A (direct / first-party, best)
Strong platform markers from the target domain itself (page source, assets, endpoints, headers/cookies if visible through tooling), e.g.:

- **Magento / Adobe Commerce**
  - `Magento_` module names, `mage/`, `form_key`, `/static/`, `/rest/V1/`, `X-Magento-*`, “Magento 2” references
- **Shopware**
  - `/bundles/storefront/`, `/widgets/`, Shopware storefront bundle patterns, “Shopware 6” references
- **WooCommerce**
  - `wp-content/plugins/woocommerce`, `woocommerce_params`, `/wp-json/wc/`, “WooCommerce” assets
- **Shopify**
  - `cdn.shopify.com`, `myshopify.com`, `Shopify.theme`, `shopify-section`, theme JSON endpoints

Rule: If Tier A signals exist for a platform, they override Tier B/C if contradictory.

### Tier B (strong, third-party)
Reputable technology profiler sources (e.g. BuiltWith, Wappalyzer, SimilarTech), ideally **2+ sources agree** for high confidence.

### Tier C (weak/indirect)
Indirect hints only (single low-quality directory listing, vague blog mention, agency case study not clearly tied to the domain, job postings without domain confirmation).

---

## Decision rules (avoid common failure modes)

- **Shop presence semantics (lead qualification)**:
  - set `shop_presence=shop` if you have evidence that an ecommerce platform is present on the target domain or a clearly-linked shop subdomain under the same root (even if the storefront is limited/coming-soon).
  - if the only “checkout” is handled entirely by a third-party service (e.g. event registration/donation platforms like eveeno/betterplace) and the target domain does **not** run an ecommerce platform itself, set `shop_presence=not_shop`.
  - set `shop_presence=not_shop` only if the domain appears purely informational/lead-gen with no evidence of ecommerce platform presence or shop intent.
  - set `shop_presence=unclear` if you cannot determine.
- **Target-domain specificity**: evidence must be about the provided domain, not an agency’s other clients.
- **Conflicts**: if signals disagree and you can’t resolve, output `unknown` with low confidence.
- **Dead/blocked/parked/ambiguous**: output `unknown` with low confidence.
- **No URL leakage**: never include raw URLs in `reasoning` (URLs may only appear in optional debug `sources`).

---

## Confidence mapping (must be consistent)

- **high**: Tier A, or Tier B with strong agreement across reputable sources
- **medium**: Tier B single source, or multiple Tier C hints that align
- **low**: Tier C only, conflicting signals, or `unknown`


