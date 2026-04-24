"""
Layer 4 — Smurf pattern detector
Pure rule-based — no AI cost here.
Flags clusters that match known smurfing signatures.

Rules applied:
  R1 — Star pattern: node receives from >= MIN_SENDERS distinct sources
  R2 — Amount similarity: std-dev of incoming amounts < AMOUNT_STD_THRESHOLD
  R3 — Time compression: all incoming edges within TIME_WINDOW_HOURS
  R4 — Below-threshold: all individual amounts < THRESHOLD_AMOUNT (structuring)
"""

import statistics
from collections import defaultdict
from datetime import datetime, timedelta

# Tunable thresholds
MIN_SENDERS          = 4       # minimum distinct senders to one node
THRESHOLD_AMOUNT     = 500.0   # EUR — structuring signal if all below this
AMOUNT_STD_THRESHOLD = 80.0    # EUR std-dev — similar amounts = coordinated
TIME_WINDOW_HOURS    = 24      # hours to look back


class SmurfCluster:
    def __init__(self, target_node, senders, amounts, timestamps, score):
        self.target_node  = target_node
        self.senders      = senders
        self.amounts      = amounts
        self.timestamps   = timestamps
        self.score        = score          # 0–100 risk score
        self.total        = sum(amounts)
        self.rules_fired  = []

    def to_dict(self):
        return {
            "target": self.target_node,
            "senders": self.senders,
            "num_senders": len(self.senders),
            "amounts": self.amounts,
            "total_eur": round(self.total, 2),
            "score": self.score,
            "rules_fired": self.rules_fired,
        }


def detect(G, transactions: list[dict]) -> list[SmurfCluster]:
    """
    Run all four rules against the graph.
    Returns list of SmurfCluster objects sorted by risk score desc.
    """
    # Build per-node incoming edge list with metadata
    incoming = defaultdict(list)   # node -> [{sender, amount, created}]

    for tx in transactions:
        dst   = tx.get("to_iban", "unknown")
        src   = tx.get("from_iban", "unknown")
        try:
            amount = float(tx.get("amount", 0))
        except (ValueError, TypeError):
            amount = 0.0
        created = tx.get("created", "")
        incoming[dst].append({"sender": src, "amount": amount, "created": created})

    clusters = []

    for node, edges in incoming.items():
        senders = list({e["sender"] for e in edges})
        amounts = [e["amount"] for e in edges]

        # R1 — Star pattern check
        if len(senders) < MIN_SENDERS:
            continue

        cluster = SmurfCluster(
            target_node=node,
            senders=senders,
            amounts=amounts,
            timestamps=[e["created"] for e in edges],
            score=0,
        )

        score = 0
        rules = []

        # R1 — Star pattern
        score += min(40, len(senders) * 8)
        rules.append(f"R1:star({len(senders)} senders)")

        # R2 — Amount similarity
        if len(amounts) >= 2:
            std = statistics.stdev(amounts)
            if std < AMOUNT_STD_THRESHOLD:
                score += 25
                rules.append(f"R2:similar_amounts(std={std:.1f})")

        # R3 — Time compression
        timestamps = []
        for e in edges:
            try:
                timestamps.append(
                    datetime.fromisoformat(e["created"].replace(" ", "T"))
                )
            except Exception:
                pass
        if len(timestamps) >= 2:
            span = (max(timestamps) - min(timestamps)).total_seconds() / 3600
            if span <= TIME_WINDOW_HOURS:
                score += 20
                rules.append(f"R3:compressed({span:.1f}h window)")

        # R4 — Below threshold structuring
        if amounts and all(a < THRESHOLD_AMOUNT for a in amounts):
            score += 15
            rules.append(f"R4:below_threshold(all<€{THRESHOLD_AMOUNT})")

        cluster.score = min(score, 100)
        cluster.rules_fired = rules
        clusters.append(cluster)

    return sorted(clusters, key=lambda c: c.score, reverse=True)
