"""
Layer 2 — Privacy anonymiser
Based on: Ghosh, K. (2025). Privacy-First Healthcare Coordination.
Zenodo. https://doi.org/10.5281/zenodo.17440767

Same pattern applied to banking: replace all real IBANs / account IDs
with one-way SHA-256 hashes. The graph never touches PII.
The reverse map stays in memory only — never written to disk.
"""

import hashlib
import hmac
import os

# Per-run salt — changes every execution so hashes can't be
# precomputed across runs. In production, use a stable HSM-backed key.
_SALT = os.urandom(32)

# In-memory reverse map for demo display only
_reverse: dict[str, str] = {}


def anonymise(identifier: str) -> str:
    """Return a stable 16-char hex token for this run."""
    h = hmac.new(_SALT, identifier.encode(), hashlib.sha256).hexdigest()[:16]
    _reverse[h] = identifier
    return h


def deanonymise(token: str) -> str:
    """Look up the original value (demo only — never expose in prod)."""
    return _reverse.get(token, token)


def anonymise_transaction(tx: dict) -> dict:
    """Return a copy of the transaction with IBANs replaced by tokens."""
    return {
        **tx,
        "from_iban": anonymise(tx.get("from_iban") or "unknown"),
        "to_iban":   anonymise(tx.get("to_iban")   or "unknown"),
        "from_name": "[REDACTED]",
        "to_name":   "[REDACTED]",
    }


def anonymise_all(transactions: list[dict]) -> list[dict]:
    return [anonymise_transaction(t) for t in transactions]
