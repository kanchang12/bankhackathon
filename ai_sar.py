"""
Layer 5 - Multimodal AI (OpenAI)
Uses gpt-4o which has vision built in.
Sends graph image + cluster stats -> structured SAR report.

Model: gpt-4o
Pricing: $2.50/M input, $10/M output
Cost per SAR: ~$0.003
"""

import os
import json
import time
import base64
from datetime import datetime, timezone
from openai import OpenAI

MODEL = "gpt-4o"
INPUT_PRICE_PER_M  = 2.50
OUTPUT_PRICE_PER_M = 10.00
USD_TO_EUR         = 0.92


def _make_client(api_key=None):
    key = api_key or os.environ.get("OPENAI_API_KEY")
    if not key:
        raise ValueError("OPENAI_API_KEY not set.")
    return OpenAI(api_key=key)


def generate_sar(cluster, graph_image_bytes, client=None):
    if client is None:
        client = _make_client()

    cluster_dict = cluster.to_dict()
    img_b64 = base64.standard_b64encode(graph_image_bytes).decode()

    system_prompt = (
        "You are a financial crime compliance analyst specialising in AML. "
        "You receive a transaction network graph image and structured cluster data. "
        "Respond ONLY with valid JSON - no markdown, no code fences, no extra text."
    )

    user_content = [
        {
            "type": "image_url",
            "image_url": {
                "url": f"data:image/png;base64,{img_b64}",
                "detail": "high"
            }
        },
        {
            "type": "text",
            "text": f"""Analyse this transaction network graph and cluster data.
Red nodes are flagged smurf targets. Edge labels show EUR amounts.

CLUSTER DATA:
{json.dumps(cluster_dict, indent=2)}

Rules fired: {', '.join(cluster_dict['rules_fired'])}
Total value: EUR {cluster_dict['total_eur']}
Distinct senders: {cluster_dict['num_senders']}
Risk score: {cluster_dict['score']}/100

Return a SAR JSON with these exact fields:
- reference: string SAR-YYYY-XXXX
- risk_score: integer 0-100
- pattern_type: SMURFING | LAYERING | STRUCTURING | UNKNOWN
- summary: 2-3 sentences describing what the graph shows
- indicators: array of specific red flags observed
- recommended_action: FREEZE | ESCALATE | MONITOR | DISMISS
- visual_observation: one sentence on the network shape you see
- confidence: HIGH | MEDIUM | LOW"""
        }
    ]

    t0 = time.time()
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_content}
        ],
        max_tokens=1000,
        temperature=0.1,
        response_format={"type": "json_object"}
    )
    elapsed = time.time() - t0

    raw = response.choices[0].message.content.strip()
    try:
        sar = json.loads(raw)
    except json.JSONDecodeError:
        sar = {"raw_response": raw, "parse_error": True}

    input_tokens  = response.usage.prompt_tokens
    output_tokens = response.usage.completion_tokens
    cost_usd = (input_tokens * INPUT_PRICE_PER_M + output_tokens * OUTPUT_PRICE_PER_M) / 1_000_000
    cost_eur = cost_usd * USD_TO_EUR

    sar["_meta"] = {
        "generated_at":    datetime.now(timezone.utc).isoformat(),
        "model":           MODEL,
        "input_tokens":    input_tokens,
        "output_tokens":   output_tokens,
        "cost_usd":        round(cost_usd, 6),
        "cost_eur":        round(cost_eur, 6),
        "latency_seconds": round(elapsed, 2),
        "cluster_target":  cluster.target_node,
    }
    return sar


def print_sar(sar):
    meta = sar.pop("_meta", {})
    print("\n" + "=" * 62)
    print("  SUSPICIOUS ACTIVITY REPORT")
    print("=" * 62)
    for k, v in sar.items():
        if k in {"parse_error", "raw_response"}:
            continue
        if isinstance(v, list):
            print(f"\n  {k.upper()}:")
            for item in v:
                print(f"    - {item}")
        else:
            print(f"\n  {k.upper()}: {v}")
    print("\n" + "-" * 62)
    print(f"  Model    : {meta.get('model')}")
    print(f"  Tokens   : {meta.get('input_tokens')} in / {meta.get('output_tokens')} out")
    print(f"  Cost     : EUR {meta.get('cost_eur')} (${meta.get('cost_usd')})")
    print(f"  Latency  : {meta.get('latency_seconds')}s")
    print("=" * 62)
    sar["_meta"] = meta
