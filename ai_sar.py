"""
Layer 5 — Multimodal AI (Gemini)
Uses the new google-genai SDK (v1.x) with Gemini 2.0 Flash.

Sends the rendered graph IMAGE to Gemini vision.
Gemini reads the visual network structure + cluster stats -> writes SAR.

Multimodal modality satisfied:
  image (graph PNG) + text (cluster stats) -> structured SAR report

Model: gemini-2.0-flash
Pricing: $0.075/M input tokens . $0.30/M output tokens
Cost per SAR: ~$0.001 (~EUR 0.001)
"""

import os
import json
import time
from datetime import datetime, timezone

from google import genai
from google.genai import types


MODEL = "gemini-2.0-flash"

INPUT_PRICE_PER_M  = 0.075
OUTPUT_PRICE_PER_M = 0.30
USD_TO_EUR         = 0.92


def _make_client(api_key=None):
    key = api_key or os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not key:
        raise ValueError(
            "No Gemini API key found. "
            "Set GOOGLE_API_KEY or GEMINI_API_KEY environment variable."
        )
    return genai.Client(api_key=key)


def generate_sar(cluster, graph_image_bytes, client=None):
    """
    Send graph PNG image + cluster stats to Gemini 2.0 Flash.
    Returns structured SAR dict with cost metadata.
    """
    if client is None:
        client = _make_client()

    cluster_dict = cluster.to_dict()

    system_instruction = (
        "You are a financial crime compliance analyst specialising in AML. "
        "You receive a transaction network graph image and structured cluster data. "
        "You write Suspicious Activity Reports (SARs). "
        "Respond ONLY with valid JSON - no markdown, no code fences, no extra text."
    )

    prompt_text = f"""Analyse this transaction network graph image and the cluster data below.
The image shows accounts as nodes and money transfers as directed edges.
Red nodes are flagged as smurf targets. Edge labels show EUR amounts.

CLUSTER DATA:
{json.dumps(cluster_dict, indent=2)}

Rules that fired: {', '.join(cluster_dict['rules_fired'])}
Total incoming value: EUR {cluster_dict['total_eur']}
Distinct senders: {cluster_dict['num_senders']}
Rule-based risk score: {cluster_dict['score']}/100

Write a SAR as a JSON object with these exact fields:
- reference: string, format SAR-YYYY-XXXX
- risk_score: integer 0-100
- pattern_type: one of SMURFING | LAYERING | STRUCTURING | UNKNOWN
- summary: string, 2-3 sentences describing what the graph visually shows
- indicators: array of strings, specific red flags observed
- recommended_action: one of FREEZE | ESCALATE | MONITOR | DISMISS
- visual_observation: one sentence describing the network shape in the image
- confidence: one of HIGH | MEDIUM | LOW"""

    contents = [
        types.Part.from_bytes(data=graph_image_bytes, mime_type="image/png"),
        types.Part.from_text(text=prompt_text),
    ]

    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=0.1,
        max_output_tokens=1024,
        response_mime_type="application/json",
    )

    t0 = time.time()
    response = client.models.generate_content(
        model=MODEL,
        contents=contents,
        config=config,
    )
    elapsed = time.time() - t0

    raw = response.text.strip() if response.text else "{}"
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        if raw.startswith("json"):
            raw = raw[4:].strip()

    try:
        sar = json.loads(raw)
    except json.JSONDecodeError:
        sar = {"raw_response": raw, "parse_error": True}

    usage = response.usage_metadata
    input_tokens  = getattr(usage, "prompt_token_count", 0) or 0
    output_tokens = getattr(usage, "candidates_token_count", 0) or 0
    cost_usd = (input_tokens  * INPUT_PRICE_PER_M  / 1_000_000 +
                output_tokens * OUTPUT_PRICE_PER_M / 1_000_000)
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
