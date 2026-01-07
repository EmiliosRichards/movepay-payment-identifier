## SHOPTECH: Ecommerce Platform Detector (OpenAI Responses API + Web Search)

This repo detects which ecommerce platform a shop uses:
`magento | shopware | woocommerce | shopify | other | unknown`

It uses a **single OpenAI Responses API call** with **Web Search** enabled (optionally Flex + prompt caching) and writes **incremental JSONL + CSV** outputs including **usage + cost + tool-call metadata**.

### Install

```bash
python -m pip install -r requirements.txt
```

### Configure

Copy the template and set at least `OPENAI_API_KEY`:

```bash
copy env_example.md .env
```

Key env vars (prefix is **`SHOPTECH_`**):
- **Tool budget**: `SHOPTECH_MAX_TOOL_CALLS`, `SHOPTECH_SECOND_QUERY_ON_UNCERTAINTY`
- **Gated retry (optional, off by default)**: `SHOPTECH_RETRY_DISAMBIGUATION_ON_LOW_CONFIDENCE`, `SHOPTECH_RETRY_MAX_TOOL_CALLS`
- **Flex**: `SHOPTECH_SERVICE_TIER=flex`, `SHOPTECH_OPENAI_TIMEOUT_SECONDS`, `SHOPTECH_FLEX_*`, `SHOPTECH_FLEX_TOKEN_DISCOUNT`
- **Prompt caching**: `SHOPTECH_PROMPT_CACHE`, `SHOPTECH_PROMPT_CACHE_RETENTION`
- **Pricing (for reporting)**: `SHOPTECH_PRICE_INPUT_PER_1M`, `SHOPTECH_PRICE_CACHED_INPUT_PER_1M`, `SHOPTECH_PRICE_OUTPUT_PER_1M`, `SHOPTECH_PRICE_WEB_SEARCH_PER_1K`

### Run

- **Single URL**:

```bash
python -m scripts.evaluate https://example.com
```

- **List runner (CSV/TXT → JSONL + CSV)**:

```bash
python -m scripts.evaluate_list --input data/shops.csv --url-column Website --name-column Name --resume
```

- **Observability**
  - Trace web-search behavior: `python -m scripts.trace_web_search --input data/shops.csv --sample 25 --include-sources`
  - Analyze a run CSV: `python -m scripts.analyze_run --csv outputs/<run>.csv`

### Output contract (strict JSON Schema)

The model output is enforced via strict JSON Schema in `shoptech_eval/schema.py`:
- `input_url`
- `final_platform`
- `confidence`
- `evidence_tier`
- `signals`
- `reasoning` (≤600 chars, 2–4 sentences, **no raw URLs**)

### Notes on billing semantics

- **Web search tool billing** is estimated from **query-type** web searches (not total tool invocations).
- **Flex discount** (if enabled) is applied to **token cost only**, not web-search tool cost.

See `docs/USAGE.md` for flags, env defaults, and recommended presets.


