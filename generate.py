#!/usr/bin/env python3
"""Build a LiteLLM cost map that is upstream + our OpenRouter routes.

The upstream map (BerriAI/litellm model_prices_and_context_window.json) covers
~3,000 models but NOT the `openrouter/...`-prefixed routes we route through the
proxy. This script downloads the upstream map, then overwrites the handful of
OpenRouter routes we actually use with live prices from openrouter.ai, and
writes the merged result to model_prices_and_context_window.json.

Run locally or via .github/workflows/sync.yml (weekly, cloud-side).
"""
import json
import os
import sys
import urllib.request

UPSTREAM_URL = os.environ.get(
    "LITELLM_UPSTREAM_URL",
    "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json",
)
OPENROUTER_URL = "https://openrouter.ai/api/v1/models"
OUTPUT = "model_prices_and_context_window.json"

# OpenRouter model IDs we route through LiteLLM. The cost-map key for each is
# the id prefixed with `openrouter/`. Add new OpenRouter routes here.
TARGETS = [
    "anthropic/claude-sonnet-5",
    "deepseek/deepseek-v4-flash-0731",
    "moonshotai/kimi-k3",
]


def get(url):
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.load(r)


def main():
    print(f"Fetching upstream cost map: {UPSTREAM_URL}")
    cost_map = get(UPSTREAM_URL)
    print(f"  upstream entries: {len(cost_map)}")

    print(f"Fetching OpenRouter prices: {OPENROUTER_URL}")
    or_by_id = {m["id"]: m for m in get(OPENROUTER_URL).get("data", [])}

    changed = []
    missing = []
    for or_id in TARGETS:
        m = or_by_id.get(or_id)
        if not m:
            missing.append(or_id)
            continue
        p = m.get("pricing") or {}
        prompt, completion = p.get("prompt"), p.get("completion")
        if prompt is None or completion is None:
            missing.append(or_id)
            continue
        top = m.get("top_provider") or {}
        key = "openrouter/" + or_id
        entry = {
            "max_tokens": m.get("context_length") or 32768,
            "max_input_tokens": m.get("context_length"),
            "max_output_tokens": top.get("max_completion_tokens"),
            "input_cost_per_token": float(prompt),
            "output_cost_per_token": float(completion),
            "litellm_provider": "openrouter",
            "mode": "chat",
        }
        entry = {k: v for k, v in entry.items() if v is not None}
        old = cost_map.get(key)
        cost_map[key] = entry
        if old != entry:
            changed.append((key, float(prompt) * 1e6, float(completion) * 1e6))

    with open(OUTPUT, "w") as f:
        json.dump(cost_map, f, separators=(",", ":"))
        f.write("\n")

    print(f"Wrote {OUTPUT}: {len(cost_map)} entries ({len(TARGETS)} OpenRouter routes ensured)")
    for key, pm, cm in changed:
        print(f"  set {key}: ${pm:.4f}/M in, ${cm:.4f}/M out")
    for or_id in missing:
        print(f"  WARN: {or_id} not priced on OpenRouter; left untouched")
    if not changed:
        print("  no price changes vs previous build")
    return 0


if __name__ == "__main__":
    sys.exit(main())
