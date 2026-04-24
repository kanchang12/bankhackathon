"""
SmurfDetect — Flask web app
Deploy on Koyeb with: gunicorn app:app

Environment variables required:
  GOOGLE_API_KEY   — Gemini API key
  BUNQ_API_KEY     — bunq sandbox/production key (optional, uses demo data if missing)
"""

import os
import json
import base64
import threading
from datetime import datetime, timezone
from flask import Flask, render_template, jsonify, request

from privacy       import anonymise_all
from graph_engine  import build_graph, render_graph_to_bytes
from smurf_detector import detect

app = Flask(__name__)

# ── In-memory state (single-user demo) ──────────────────────────────────────
state = {
    "status":       "idle",       # idle | running | done | error
    "last_run":     None,
    "transactions": 0,
    "clusters":     [],
    "sars":         [],
    "graph_b64":    None,
    "total_cost":   0.0,
    "error":        None,
    "run_count":    0,
}
_lock = threading.Lock()


# ── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/state")
def api_state():
    with _lock:
        return jsonify(state)


@app.route("/api/scan", methods=["POST"])
def api_scan():
    with _lock:
        if state["status"] == "running":
            return jsonify({"error": "scan already running"}), 409
        state["status"] = "running"
        state["error"]  = None

    t = threading.Thread(target=_run_pipeline, daemon=True)
    t.start()
    return jsonify({"started": True})


# ── Pipeline ─────────────────────────────────────────────────────────────────

def _run_pipeline():
    try:
        raw_txs = _fetch_transactions()

        anon_txs = anonymise_all(raw_txs)

        G = build_graph(anon_txs, hours_window=48)

        clusters = detect(G, anon_txs)

        flagged = {c.target_node for c in clusters}
        img_bytes = render_graph_to_bytes(
            G, flagged_nodes=flagged,
            title=f"SmurfDetect — {len(clusters)} cluster(s) flagged"
        )
        graph_b64 = base64.b64encode(img_bytes).decode()

        sars = []
        total_cost = 0.0
        google_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")

        if google_key and clusters:
            from google import genai
            from ai_sar import generate_sar
            client = genai.Client(api_key=google_key)
            for cluster in clusters[:5]:
                try:
                    sar = generate_sar(cluster, img_bytes, client)
                    total_cost += sar.get("_meta", {}).get("cost_eur", 0)
                    sars.append(sar)
                except Exception as e:
                    sars.append({
                        "error": str(e),
                        "cluster_target": cluster.target_node,
                        "score": cluster.score,
                    })
        else:
            # Demo SAR when no API key
            for cluster in clusters:
                sars.append(_demo_sar(cluster))

        with _lock:
            state.update({
                "status":       "done",
                "last_run":     datetime.now(timezone.utc).isoformat(),
                "transactions": len(raw_txs),
                "clusters":     [c.to_dict() for c in clusters],
                "sars":         sars,
                "graph_b64":    graph_b64,
                "total_cost":   round(total_cost, 6),
                "error":        None,
                "run_count":    state["run_count"] + 1,
            })

    except Exception as e:
        import traceback
        with _lock:
            state["status"] = "error"
            state["error"]  = traceback.format_exc()


def _fetch_transactions():
    api_key = os.environ.get("BUNQ_API_KEY")
    if api_key:
        try:
            from bunq_auth import setup_session, get_monetary_accounts, get_payments
            session_token, user_id = setup_session(api_key)
            accounts = get_monetary_accounts(session_token, user_id)
            txs = []
            for acct in accounts:
                txs.extend(get_payments(session_token, user_id, acct["id"], count=50))
            if txs:
                return txs
        except Exception:
            pass
    return _demo_transactions()


def _demo_transactions():
    import random
    from datetime import timedelta
    base  = datetime.now(timezone.utc)
    target = "NL91BUNQ0000000001"
    smurfs = [f"NL91BUNQ000000{i:04d}" for i in range(2, 12)]
    txs = []
    for i, src in enumerate(smurfs[:8]):
        txs.append({
            "id": i + 1,
            "from_iban": src,
            "to_iban":   target,
            "amount":    str(round(random.uniform(420, 499), 2)),
            "currency":  "EUR",
            "created":   (base - timedelta(hours=random.uniform(0, 20))).isoformat(),
            "type":      "PAYMENT",
        })
    for i in range(4):
        txs.append({
            "id": 100 + i,
            "from_iban": smurfs[0],
            "to_iban":   smurfs[1],
            "amount":    str(round(random.uniform(50, 2000), 2)),
            "currency":  "EUR",
            "created":   (base - timedelta(hours=random.uniform(0, 48))).isoformat(),
            "type":      "PAYMENT",
        })
    return txs


def _demo_sar(cluster):
    d = cluster.to_dict()
    return {
        "reference":          f"SAR-{datetime.now().year}-DEMO",
        "risk_score":         d["score"],
        "pattern_type":       "SMURFING",
        "summary":            (
            f"A star-shaped transaction network was detected with {d['num_senders']} "
            f"distinct accounts sending funds to a single target within 24 hours. "
            f"All individual amounts fall below the €500 reporting threshold, "
            f"a classic structuring indicator."
        ),
        "indicators": [
            f"{d['num_senders']} senders converging on one account",
            f"Total value €{d['total_eur']} split into sub-threshold amounts",
            "Transactions clustered within a compressed time window",
            "Amount variance low — coordinated behaviour suspected",
        ],
        "recommended_action": "ESCALATE",
        "visual_observation": "Clear star topology visible in graph — all edges point inward to one red node.",
        "confidence":         "HIGH",
        "_meta": {
            "model":   "demo-mode",
            "cost_eur": 0.0,
            "note":    "Set GOOGLE_API_KEY for real Gemini SAR generation",
        },
    }


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
