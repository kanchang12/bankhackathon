"""
Layer 3 — Graph engine
Builds a directed transaction graph from anonymised payments.
Renders to PNG for the multimodal AI layer.
"""

import networkx as nx
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from datetime import datetime, timedelta
from collections import defaultdict
import io


def build_graph(transactions: list[dict], hours_window: int = 24) -> nx.DiGraph:
    """
    Build directed graph: node = anonymised IBAN, edge = payment.
    Filters to transactions within hours_window of the most recent tx.
    """
    G = nx.DiGraph()

    if not transactions:
        return G

    # Find time window
    times = []
    for tx in transactions:
        try:
            times.append(datetime.fromisoformat(tx["created"].replace(" ", "T")))
        except Exception:
            pass

    cutoff = (max(times) - timedelta(hours=hours_window)) if times else None

    for tx in transactions:
        try:
            ts = datetime.fromisoformat(tx["created"].replace(" ", "T"))
        except Exception:
            ts = datetime.now()

        if cutoff and ts < cutoff:
            continue

        src = tx.get("from_iban", "unknown")
        dst = tx.get("to_iban", "unknown")
        amount = float(tx.get("amount", 0))

        if not G.has_node(src):
            G.add_node(src, label=src[:8])
        if not G.has_node(dst):
            G.add_node(dst, label=dst[:8])

        if G.has_edge(src, dst):
            G[src][dst]["total"] += amount
            G[src][dst]["count"] += 1
            G[src][dst]["amounts"].append(amount)
        else:
            G.add_edge(src, dst, total=amount, count=1, amounts=[amount],
                       created=tx.get("created", ""))

    return G


def get_in_degree_map(G: nx.DiGraph) -> dict:
    return dict(G.in_degree())


def render_graph_to_bytes(G: nx.DiGraph, flagged_nodes: set = None,
                           title: str = "Transaction network") -> bytes:
    """
    Render the graph as a PNG and return raw bytes.
    Flagged nodes shown in red — this is the image sent to Claude.
    """
    flagged_nodes = flagged_nodes or set()

    fig, ax = plt.subplots(figsize=(10, 8), facecolor="#0f1117")
    ax.set_facecolor("#0f1117")

    if len(G.nodes) == 0:
        ax.text(0.5, 0.5, "No transactions in window",
                ha="center", va="center", color="white", fontsize=14)
        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=150, bbox_inches="tight",
                    facecolor="#0f1117")
        plt.close()
        return buf.getvalue()

    pos = nx.spring_layout(G, seed=42, k=2.5)

    node_colors = []
    node_sizes = []
    in_deg = get_in_degree_map(G)

    for n in G.nodes:
        if n in flagged_nodes:
            node_colors.append("#E24B4A")
            node_sizes.append(800 + in_deg.get(n, 1) * 200)
        elif in_deg.get(n, 0) > 2:
            node_colors.append("#EF9F27")
            node_sizes.append(500 + in_deg.get(n, 1) * 150)
        else:
            node_colors.append("#378ADD")
            node_sizes.append(300)

    nx.draw_networkx_nodes(G, pos, ax=ax, node_color=node_colors,
                           node_size=node_sizes, alpha=0.9)
    nx.draw_networkx_edges(G, pos, ax=ax, edge_color="#5DCAA5",
                           arrows=True, arrowsize=15, alpha=0.6,
                           connectionstyle="arc3,rad=0.1",
                           width=1.2)

    labels = {n: n[:8] for n in G.nodes}
    nx.draw_networkx_labels(G, pos, labels, ax=ax,
                            font_color="white", font_size=7)

    edge_labels = {}
    for u, v, d in G.edges(data=True):
        edge_labels[(u, v)] = f"€{d['total']:.0f}"
    nx.draw_networkx_edge_labels(G, pos, edge_labels, ax=ax,
                                  font_color="#9FE1CB", font_size=6)

    legend_patches = [
        mpatches.Patch(color="#E24B4A", label="Flagged — possible smurf target"),
        mpatches.Patch(color="#EF9F27", label="High in-degree — watch"),
        mpatches.Patch(color="#378ADD", label="Normal node"),
    ]
    ax.legend(handles=legend_patches, loc="upper left",
              facecolor="#1a1d27", edgecolor="#5F5E5A",
              labelcolor="white", fontsize=8)

    ax.set_title(title, color="white", fontsize=13, pad=12)
    ax.axis("off")

    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=150, bbox_inches="tight",
                facecolor="#0f1117")
    plt.close()
    buf.seek(0)
    return buf.getvalue()


def save_graph_image(G: nx.DiGraph, path: str,
                      flagged_nodes: set = None, title: str = "Transaction network"):
    img_bytes = render_graph_to_bytes(G, flagged_nodes, title)
    with open(path, "wb") as f:
        f.write(img_bytes)
    return path
