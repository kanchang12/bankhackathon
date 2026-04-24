"""
SmurfDetect — Flask web app
Deploy on Koyeb: gunicorn app:app

Env vars:
  OPENAI_API_KEY  — OpenAI API key (gpt-4o)
  BUNQ_API_KEY    — bunq sandbox key (optional, uses demo data if missing)
"""

import os
import json
import base64
import threading
from datetime import datetime, timezone
from flask import Flask, render_template, jsonify, request

from privacy         import anonymise_all
from graph_engine    import build_graph, render_graph_to_bytes
from smurf_detector  import detect
from image_extractor import extract_transactions_from_image

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024  # 10MB

state = {
    "status":           "idle",
    "last_run":         None,
    "transactions":     0,
    "clusters":         [],
    "sars":             [],
    "graph_b64":        None,
    "total_cost":       0.0,
    "error":            None,
    "run_count":        0,
    "upload_status":    "idle",
    "upload_filename":  None,
    "upload_txns":      [],
    "upload_count":     0,
    "upload_cost":      0.0,
    "upload_error":     None,
    "upload_image_b64": None,
}
_lock = threading.Lock()


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
        injected = list(state.get("upload_txns", []))
    t = threading.Thread(target=_run_pipeline, args=(injected,), daemon=True)
    t.start()
    return jsonify({"started": True})


@app.route("/api/upload", methods=["POST"])
def api_upload():
    if "file" not in request.files:
        return jsonify({"error": "no file provided"}), 400
    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "empty filename"}), 400
    mime = f.content_type or "image/jpeg"
    if mime not in {"image/jpeg", "image/png", "image/webp", "image/gif"}:
        return jsonify({"error": f"unsupported type {mime}"}), 400
    img_bytes = f.read()
    img_b64   = base64.b64encode(img_bytes).decode()
    with _lock:
        state["upload_status"]    = "processing"
        state["upload_filename"]  = f.filename
        state["upload_image_b64"] = img_b64
        state["upload_error"]     = None
        state["upload_txns"]      = []
    t = threading.Thread(target=_process_upload, args=(img_bytes, mime), daemon=True)
    t.start()
    return jsonify({"started": True, "filename": f.filename})


def _process_upload(img_bytes, mime_type):
    try:
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise ValueError("OPENAI_API_KEY not set")
        from openai import OpenAI
        client = OpenAI(api_key=key)
        result = extract_transactions_from_image(img_bytes, mime_type, client)
        with _lock:
            state["upload_status"] = "done"
            state["upload_txns"]   = result["transactions"]
            state["upload_count"]  = result["count"]
            state["upload_cost"]   = result["cost_eur"]
            state["upload_error"]  = None
    except Exception as e:
        with _lock:
            state["upload_status"] = "error"
            state["upload_error"]  = str(e)
            state["upload_txns"]   = []


def _run_pipeline(injected_txns=None):
    try:
        raw_txs = injected_txns if injected_txns else _fetch_transactions()
        anon_txs = anonymise_all(raw_txs)
        G = build_graph(anon_txs, hours_window=48)
        clusters = detect(G, anon_txs)
        flagged   = {c.target_node for c in clusters}
        img_bytes = render_graph_to_bytes(
            G, flagged_nodes=flagged,
            title=f"SmurfDetect — {len(clusters)} cluster(s) flagged"
        )
        graph_b64 = base64.b64encode(img_bytes).decode()

        sars = []
        total_cost = 0.0
        key = os.environ.get("OPENAI_API_KEY")

        if key and clusters:
            from openai import OpenAI
            from ai_sar import generate_sar
            client = OpenAI(api_key=key)
            for cluster in clusters[:5]:
                try:
                    sar = generate_sar(cluster, img_bytes, client)
                    total_cost += sar.get("_meta", {}).get("cost_eur", 0)
                    sars.append(sar)
                except Exception as e:
                    sars.append({"error": str(e), "cluster_target": cluster.target_node, "score": cluster.score})
        else:
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
    base   = datetime.now(timezone.utc)
    target = "NL91BUNQ0000000001"
    smurfs = [f"NL91BUNQ000000{i:04d}" for i in range(2, 12)]
    txs = []
    for i, src in enumerate(smurfs[:8]):
        txs.append({
            "id": i + 1, "from_iban": src, "to_iban": target,
            "amount": str(round(random.uniform(420, 499), 2)),
            "currency": "EUR",
            "created": (base - timedelta(hours=random.uniform(0, 20))).isoformat(),
            "type": "PAYMENT",
        })
    for i in range(4):
        txs.append({
            "id": 100 + i, "from_iban": smurfs[0], "to_iban": smurfs[1],
            "amount": str(round(random.uniform(50, 2000), 2)),
            "currency": "EUR",
            "created": (base - timedelta(hours=random.uniform(0, 48))).isoformat(),
            "type": "PAYMENT",
        })
    return txs


def _demo_sar(cluster):
    d = cluster.to_dict()
    return {
        "reference": f"SAR-{datetime.now().year}-DEMO",
        "risk_score": d["score"],
        "pattern_type": "SMURFING",
        "summary": (
            f"A star-shaped transaction network was detected with {d['num_senders']} "
            f"distinct accounts sending funds to a single target within 24 hours. "
            f"All individual amounts fall below the EUR 500 reporting threshold."
        ),
        "indicators": [
            f"{d['num_senders']} senders converging on one account",
            f"Total value EUR {d['total_eur']} split into sub-threshold amounts",
            "Transactions clustered within a compressed time window",
            "Amount variance low — coordinated behaviour suspected",
        ],
        "recommended_action": "ESCALATE",
        "visual_observation": "Clear star topology — all edges point inward to one red node.",
        "confidence": "HIGH",
        "_meta": {"model": "demo-mode", "cost_eur": 0.0},
    }


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
