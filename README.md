# SmurfDetect — bunq Hackathon 7.0

**Multimodal AML detection using privacy-first graph ML + Claude vision**

Detects smurfing (structured money laundering) in bunq transaction networks.
Generates GDPR-compliant Suspicious Activity Reports using graph images + Claude.

---

## What it does

| Layer | What | Cost |
|-------|------|------|
| L1 — bunq API | Fetch transactions from sandbox | Free |
| L2 — Privacy | SHA-256 anonymise all IBANs (no PII in graph) | Free |
| L3 — Graph engine | Build NetworkX transaction network | Free |
| L4 — Smurf detector | Flag star patterns, amount clustering, time compression | Free |
| L5 — Multimodal AI | Graph image → Claude vision → SAR report | ~€0.001/SAR |

**Annual cost at 500 flags/day: ~€180. bunq's 2025 AML fine: €2,600,000.**

---

## Setup

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=your_key_here
```

---

## Run

### Option A — synthetic demo (no bunq account needed)
```bash
python main.py
```

### Option B — live bunq sandbox
```bash
# 1. Get your API key (already done if you followed setup):
curl -X POST https://public-api.sandbox.bunq.com/v1/sandbox-user-person

# 2. Set it in main.py: BUNQ_API_KEY = "sandbox_..."

# 3. Inject test smurfing data:
python sandbox_setup.py

# 4. Run detection:
python main.py
```

---

## Output

- `output/transaction_graph.png` — visual transaction network (red = flagged nodes)
- `output/sar_1.json` — structured SAR report from Claude

---

## Privacy architecture

Based on: *Ghosh, K. (2025). Privacy-First Healthcare Coordination: Anonymous
Authentication Patterns in Digital Health.* Zenodo. https://doi.org/10.5281/zenodo.17440767

Same anonymous authentication pattern adapted for banking:
- Account IDs replaced with HMAC-SHA256 tokens (per-run salt)
- No PII ever enters the graph or the AI prompt
- Reverse map held in memory only — never persisted
- GDPR compliant by design

---

## Detection rules

| Rule | Signal | Score weight |
|------|--------|-------------|
| R1 — Star pattern | ≥4 distinct senders → 1 node | +8 per sender |
| R2 — Amount similarity | StdDev < €80 across incoming | +25 |
| R3 — Time compression | All within 24h window | +20 |
| R4 — Below threshold | All amounts < €500 (structuring) | +15 |

Max score: 100. Anything above 60 triggers SAR generation.

---

## Multimodal element

The graph is rendered as a PNG image and sent to Claude's vision model alongside
the structured cluster statistics. Claude reads *both* the visual network topology
AND the numerical data to write the SAR. This satisfies the hackathon's non-text
modality requirement in a way that's genuinely useful — a human compliance officer
would do exactly the same thing: look at the network diagram and the numbers together.

---

## Project structure

```
smurfdetect/
├── main.py           # pipeline orchestrator
├── bunq_auth.py      # bunq API auth (install → device → session)
├── privacy.py        # SHA-256 anonymiser
├── graph_engine.py   # NetworkX graph + matplotlib render
├── smurf_detector.py # rule-based pattern detection
├── ai_sar.py         # Claude vision + SAR generation
├── sandbox_setup.py  # inject test smurfing data
└── requirements.txt
```
