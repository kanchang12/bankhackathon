"""
SmurfDetect — main pipeline orchestrator
Runs all 5 layers end to end and prints cost summary.

Usage:
  python main.py

Set GOOGLE_API_KEY in environment before running.
"""

import os
import sys
import json
from datetime import datetime

# ── Config ──────────────────────────────────────────────────────────────────
BUNQ_API_KEY = "sandbox_70847077b9ce2b996acb68e0c0949e89c98093b5375a95d1a7818592"
OUTPUT_DIR   = "output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ── Imports ──────────────────────────────────────────────────────────────────
from bunq_auth    import setup_session, get_monetary_accounts, get_payments
from privacy      import anonymise_all, deanonymise
from graph_engine import build_graph, save_graph_image
from smurf_detector import detect
from ai_sar       import generate_sar, print_sar
from google import genai


def run():
    total_cost_eur = 0.0
    run_start = datetime.utcnow()

    print("\n" + "="*60)
    print("  SmurfDetect — bunq Hackathon 7.0")
    print("  Multimodal AML detection using graph ML + Claude vision")
    print("="*60)

    # ── Layer 1: Fetch from bunq ─────────────────────────────────────────────
    print("\n[L1] Authenticating with bunq sandbox...")
    all_transactions = []
    try:
        session_token, user_id = setup_session(BUNQ_API_KEY)
        print(f"     Session established. User ID: {user_id}")

        accounts = get_monetary_accounts(session_token, user_id)
        for acct in accounts:
            print(f"     Fetching payments for account {acct['iban'] or acct['id']}...")
            txs = get_payments(session_token, user_id, acct["id"], count=50)
            all_transactions.extend(txs)
            print(f"     → {len(txs)} transactions found")
        print(f"\n     Total raw transactions: {len(all_transactions)}")
    except Exception as e:
        print(f"     [!] bunq unreachable ({e.__class__.__name__}). Using synthetic demo data.")
        all_transactions = []

    if not all_transactions:
        print("     Using synthetic smurfing scenario for demo...")
        all_transactions = _generate_demo_transactions()

    # ── Layer 2: Anonymise ───────────────────────────────────────────────────
    print("\n[L2] Anonymising account identifiers (SHA-256, per-run salt)...")
    anon_txs = anonymise_all(all_transactions)
    print(f"     {len(anon_txs)} transactions anonymised. No PII in graph.")

    # ── Layer 3: Build graph ─────────────────────────────────────────────────
    print("\n[L3] Building transaction graph with NetworkX...")
    G = build_graph(anon_txs, hours_window=48)
    print(f"     Nodes: {G.number_of_nodes()}  |  Edges: {G.number_of_edges()}")

    # ── Layer 4: Detect patterns ─────────────────────────────────────────────
    print("\n[L4] Running smurf pattern detection (rule-based, zero API cost)...")
    clusters = detect(G, anon_txs)
    print(f"     Clusters flagged: {len(clusters)}")

    if not clusters:
        print("\n[!]  No suspicious clusters detected in this window.")
        print("     Try running sandbox_setup.py to inject a smurfing scenario.")
        # Still render and exit gracefully
        img_path = f"{OUTPUT_DIR}/graph_clean.png"
        save_graph_image(G, img_path, title="Transaction network — no flags")
        print(f"\n     Graph saved to: {img_path}")
        return

    for i, c in enumerate(clusters):
        print(f"\n     Cluster {i+1}: target={c.target_node[:12]}..."
              f"  senders={len(c.senders)}  total=€{c.total:.2f}"
              f"  score={c.score}/100")
        print(f"       Rules: {', '.join(c.rules_fired)}")

    # ── Layer 5: Multimodal AI → SAR ─────────────────────────────────────────
    print("\n[L5] Running multimodal AI layer (graph image → Claude vision → SAR)...")

    if not (os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")):
        print("\n[!]  GOOGLE_API_KEY not set.")
        print("     Set it with: export GOOGLE_API_KEY=your_key")
        print("     Skipping SAR generation — graph images saved below.")

    client = genai.Client(api_key=os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY","")) if (os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")) else None
    flagged_set = set()
    for c in clusters:
        flagged_set.add(c.target_node)

    img_path = f"{OUTPUT_DIR}/transaction_graph.png"
    save_graph_image(G, img_path, flagged_nodes=flagged_set,
                      title=f"SmurfDetect — {len(clusters)} cluster(s) flagged")
    print(f"     Graph image saved: {img_path}")

    all_sars = []
    for i, cluster in enumerate(clusters[:3]):   # top 3 only for demo
        print(f"\n     Generating SAR for cluster {i+1} (score={cluster.score}/100)...")

        # Save cluster-specific graph
        cluster_img_path = f"{OUTPUT_DIR}/cluster_{i+1}.png"
        with open(img_path, "rb") as f:
            img_bytes = f.read()

        if client:
            sar = generate_sar(cluster, img_bytes, client)
            print_sar(sar)
            total_cost_eur += sar["_meta"]["cost_eur"]
            all_sars.append(sar)

            # Save SAR to file
            sar_path = f"{OUTPUT_DIR}/sar_{i+1}.json"
            with open(sar_path, "w") as f:
                json.dump(sar, f, indent=2)
            print(f"     SAR saved: {sar_path}")
        else:
            print(f"     [SKIP] No API key — SAR not generated")

    # ── Cost summary ──────────────────────────────────────────────────────────
    elapsed = (datetime.utcnow() - run_start).total_seconds()
    print("\n" + "="*60)
    print("  COST SUMMARY")
    print("="*60)
    print(f"  Transactions processed : {len(all_transactions)}")
    print(f"  Clusters detected      : {len(clusters)}")
    print(f"  SARs generated         : {len(all_sars)}")
    print(f"  Total AI cost this run : €{total_cost_eur:.6f}")
    if len(all_sars) > 0:
        print(f"  Cost per SAR           : €{total_cost_eur/len(all_sars):.6f}")
    print(f"  Run time               : {elapsed:.1f}s")
    print(f"\n  Annualised (est 500 flags/day):")
    daily = total_cost_eur / max(len(all_sars), 1) * 500
    print(f"    Daily  : €{daily:.2f}")
    print(f"    Annual : €{daily * 365:.2f}")
    print(f"\n  vs bunq AML fine (2025) : €2,600,000")
    print(f"  ROI ratio              : {2_600_000 / max(daily * 365, 0.01):.0f}x")
    print("="*60)


def _generate_demo_transactions():
    """Synthetic smurfing data for demo when sandbox has no transactions."""
    from privacy import anonymise
    import random
    from datetime import timedelta

    base = datetime.utcnow()
    target = "NL91BUNQ0000000001"
    normals = [f"NL91BUNQ000000{i:04d}" for i in range(2, 12)]

    txs = []
    # Smurf ring: 8 accounts → target
    for i, src in enumerate(normals[:8]):
        txs.append({
            "id": i + 1,
            "from_iban": src,
            "to_iban": target,
            "amount": str(round(random.uniform(420, 499), 2)),
            "currency": "EUR",
            "created": (base - timedelta(hours=random.uniform(0, 20))).isoformat(),
            "type": "PAYMENT",
        })
    # Normal transactions
    for i in range(5):
        txs.append({
            "id": 100 + i,
            "from_iban": normals[0],
            "to_iban": normals[1],
            "amount": str(round(random.uniform(50, 2000), 2)),
            "currency": "EUR",
            "created": (base - timedelta(hours=random.uniform(0, 48))).isoformat(),
            "type": "PAYMENT",
        })
    return txs


if __name__ == "__main__":
    run()
