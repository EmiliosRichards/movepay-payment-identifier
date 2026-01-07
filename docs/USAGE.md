## Usage Guide

This repo has three main OpenAI entrypoints:
- `python -m scripts.evaluate` (single URL)
- `python -m scripts.evaluate_list` (CSV/TXT list → JSONL + CSV)
- `python -m scripts.trace_web_search` (investigate web-search behavior; debug/audit)

### Quick presets (recommended)

- **Baseline bulk run (cheap + stable)**

```bash
# Guardrail: allow at most 2 web-search tool invocations within a single evaluation call
SHOPTECH_MAX_TOOL_CALLS=2

# Optional: Flex tier (cheaper tokens; web-search billing is separate)
SHOPTECH_SERVICE_TIER=flex
SHOPTECH_OPENAI_TIMEOUT_SECONDS=900
```

- **Sticky-company help (still usually 1 query)**

```bash
SHOPTECH_MAX_TOOL_CALLS=2
SHOPTECH_SECOND_QUERY_ON_UNCERTAINTY=1
```

- **Gated fallback retry (only on low confidence)**

```bash
SHOPTECH_MAX_TOOL_CALLS=2
SHOPTECH_RETRY_DISAMBIGUATION_ON_LOW_CONFIDENCE=1
SHOPTECH_RETRY_MAX_TOOL_CALLS=3
```

Tip: the retry is a **second model call** and can add extra web-search queries **only** on the rows that trigger it (`confidence=low`).

### `scripts.evaluate` (single shop)

Minimal:

```bash
python -m scripts.evaluate https://example.com
```

Most useful flags/envs:
- **Model/rubric**
  - env `OPENAI_MODEL` / flag `--model`
  - env `SHOPTECH_RUBRIC_FILE` / flag `--rubric-file`
- **Tool budget**
  - env `SHOPTECH_MAX_TOOL_CALLS` / flag `--max-tool-calls`
  - env `SHOPTECH_SECOND_QUERY_ON_UNCERTAINTY` / flag `--second-query-on-uncertainty`
- **Gated retry (optional)**
  - env `SHOPTECH_RETRY_DISAMBIGUATION_ON_LOW_CONFIDENCE` / flag `--retry-disambiguation-on-low-confidence`
  - env `SHOPTECH_RETRY_MAX_TOOL_CALLS` / flag `--retry-max-tool-calls`
- **Flex**
  - env `SHOPTECH_SERVICE_TIER` / flag `--service-tier`
  - env `SHOPTECH_OPENAI_TIMEOUT_SECONDS` / flag `--timeout-seconds`
  - env `SHOPTECH_FLEX_MAX_RETRIES` / flag `--flex-max-retries`
  - env `SHOPTECH_FLEX_FALLBACK_TO_AUTO` / flag `--flex-fallback-to-auto`
- **Prompt caching (optional)**
  - env `SHOPTECH_PROMPT_CACHE` / flag `--prompt-cache`
  - env `SHOPTECH_PROMPT_CACHE_RETENTION` / flag `--prompt-cache-retention`

Debug:

```bash
python -m scripts.evaluate https://example.com --debug-web-search
```

### `scripts.evaluate_list` (run a list)

Inputs:
- CSV (default): specify `--url-column` and `--name-column`
- TXT: one URL per line (`--input-format txt`)

Example: random sample of 200 unique URLs:

```bash
python -m scripts.evaluate_list ^
  --input "data/shops.csv" --input-format csv ^
  --url-column Website --name-column Name --bucket-column - ^
  --random-sample 200 --seed 42 ^
  --max-tool-calls 2 --service-tier flex --resume
```

Most useful flags/envs:
- **Input**
  - env `SHOPTECH_INPUT_PATH` / flag `--input`
  - env `SHOPTECH_INPUT_FORMAT` / flag `--input-format` (`auto/csv/txt`)
  - env `SHOPTECH_CSV_DELIMITER` / flag `--csv-delimiter`
  - env `SHOPTECH_URL_COLUMN` / flag `--url-column`
  - env `SHOPTECH_NAME_COLUMN` / flag `--name-column`
  - env `SHOPTECH_BUCKET_COLUMN` / flag `--bucket-column` (use `-` to disable)
- **Sampling / run control**
  - env `SHOPTECH_RANDOM_SAMPLE` / flag `--random-sample`
  - env `SHOPTECH_SAMPLE_SEED` / flag `--seed`
  - env `SHOPTECH_DEDUPE` / flag `--dedupe`
  - env `SHOPTECH_RESUME` / flag `--resume`
  - env `SHOPTECH_LIMIT` / flag `--limit`
  - env `SHOPTECH_CONTINUE_ON_ERROR` / flag `--continue-on-error`
  - env `SHOPTECH_PROGRESS_EVERY` / flag `--progress-every`
  - flag `--sleep` (politeness / rate limiting)
- **Model / tool budget**
  - env `OPENAI_MODEL` / flag `--model`
  - env `SHOPTECH_MAX_TOOL_CALLS` / flag `--max-tool-calls`
  - env `SHOPTECH_SECOND_QUERY_ON_UNCERTAINTY` / flag `--second-query-on-uncertainty`
  - env `SHOPTECH_RETRY_DISAMBIGUATION_ON_LOW_CONFIDENCE` / flag `--retry-disambiguation-on-low-confidence`
  - env `SHOPTECH_RETRY_MAX_TOOL_CALLS` / flag `--retry-max-tool-calls`
- **Debug/audit**
  - env `SHOPTECH_DEBUG_WEB_SEARCH` / flag `--debug-web-search` (adds query/open breakdown fields + stores `web_search_debug` in JSONL)

Tip: for “investigatory” runs, enable `--debug-web-search` and consider using `scripts.trace_web_search --include-sources` on a small sample (not bulk).

### `scripts.trace_web_search` (investigate tool behavior)

This is specifically for understanding:
- how often the model uses 1 vs 2 queries
- query vs open/visit breakdown
- optional “sources” output for auditing (increases tokens)

Example:

```bash
python -m scripts.trace_web_search ^
  --input "data/Manuav Company DE 5-30 B2B.csv" --url-column Website --name-column Company ^
  --sample 25 --seed 42 --max-tool-calls 3 --service-tier flex --include-sources
```

### Billing/cost tips (OpenAI)

- **Web search billing**: OpenAI “Web Searches” appears to bill **query** calls at **$0.01 per query**. Opens/visits still count as tool calls, but do not appear to be billed the same way.
- **Flex**: token pricing can be discounted, but **web search tool costs are not discounted**.
- **Cost fields in outputs**:
  - `web_search_calls` is the **billed query count**
  - `web_search_tool_calls_total` is total tool invocations (query + open/visit)


