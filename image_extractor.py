"""
Image extractor - user uploads bank statement/receipt photo
OpenAI gpt-4o vision reads it and extracts transaction data
That feeds directly into the smurf detector
"""

import os
import json
import time
import base64
from datetime import datetime, timezone
from openai import OpenAI

MODEL = "gpt-4o"

EXTRACT_PROMPT = """You are a financial data extraction specialist.

Look at this image carefully. It may be a bank statement, mobile banking screenshot, receipt, or transaction history.

Extract ALL visible transactions and return them as a JSON array.
Each transaction must have:
- from_iban: sender account/IBAN (use "UNKNOWN" if not visible)
- to_iban: recipient account/IBAN (use "UNKNOWN" if not visible)
- amount: numeric string e.g. "492.50"
- currency: e.g. "EUR", "GBP"
- created: ISO date string if visible, else today
- description: merchant or description if visible

If no transactions found, return [].
Respond with ONLY a valid JSON array."""


def extract_transactions_from_image(image_bytes, mime_type="image/jpeg", client=None):
    if client is None:
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise ValueError("OPENAI_API_KEY not set")
        client = OpenAI(api_key=key)

    img_b64 = base64.standard_b64encode(image_bytes).decode()

    t0 = time.time()
    response = client.chat.completions.create(
        model=MODEL,
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime_type};base64,{img_b64}",
                        "detail": "high"
                    }
                },
                {"type": "text", "text": EXTRACT_PROMPT}
            ]
        }],
        max_tokens=2048,
        temperature=0.1,
        response_format={"type": "json_object"}
    )
    elapsed = time.time() - t0

    raw = response.choices[0].message.content.strip()

    try:
        parsed = json.loads(raw)
        # handle both {"transactions": [...]} and bare [...]
        if isinstance(parsed, list):
            transactions = parsed
        elif isinstance(parsed, dict):
            transactions = parsed.get("transactions") or list(parsed.values())[0] if parsed else []
        else:
            transactions = []
    except json.JSONDecodeError:
        transactions = []

    clean = []
    for tx in transactions:
        clean.append({
            "id":          f"img_{len(clean)+1}",
            "from_iban":   str(tx.get("from_iban") or "UNKNOWN"),
            "to_iban":     str(tx.get("to_iban")   or "UNKNOWN"),
            "amount":      str(tx.get("amount", "0")),
            "currency":    str(tx.get("currency", "EUR")),
            "created":     str(tx.get("created", datetime.now(timezone.utc).isoformat())),
            "type":        "PAYMENT",
            "description": str(tx.get("description", "")),
            "source":      "image_upload",
        })

    input_tokens  = response.usage.prompt_tokens
    output_tokens = response.usage.completion_tokens
    cost_usd = (input_tokens * 2.50 + output_tokens * 10.00) / 1_000_000
    cost_eur = cost_usd * 0.92

    return {
        "transactions":    clean,
        "count":           len(clean),
        "model":           MODEL,
        "input_tokens":    input_tokens,
        "output_tokens":   output_tokens,
        "cost_eur":        round(cost_eur, 6),
        "latency_seconds": round(elapsed, 2),
        "extracted_at":    datetime.now(timezone.utc).isoformat(),
    }
