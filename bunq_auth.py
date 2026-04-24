"""
Layer 1 — bunq API authentication
3-step flow: installation → device-server → session-server
Returns session_token + user_id for all subsequent calls
"""

import json
import requests
import base64
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.backends import default_backend

SANDBOX_BASE = "https://public-api.sandbox.bunq.com/v1"

def generate_rsa_keypair():
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend()
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()
    return private_key, public_pem


def _extract(response_list, key):
    for item in response_list:
        if key in item:
            return item[key]
    return None


def setup_session(api_key):
    """
    Full bunq auth flow. Returns (session_token, user_id).
    Call once per run — session lasts 1 week in sandbox.
    """
    private_key, public_pem = generate_rsa_keypair()

    # Step 1: Installation — register our public key
    r = requests.post(
        f"{SANDBOX_BASE}/installation",
        json={"client_public_key": public_pem},
        headers={"Content-Type": "application/json"}
    )
    r.raise_for_status()
    resp = r.json()["Response"]
    installation_token = _extract(resp, "Token")["token"]

    # Step 2: Device server — bind API key to this device
    r = requests.post(
        f"{SANDBOX_BASE}/device-server",
        json={
            "description": "SmurfDetect-Hackathon",
            "secret": api_key,
            "permitted_ips": ["*"]
        },
        headers={
            "Content-Type": "application/json",
            "X-Bunq-Client-Authentication": installation_token
        }
    )
    r.raise_for_status()

    # Step 3: Session server — get session token
    r = requests.post(
        f"{SANDBOX_BASE}/session-server",
        json={"secret": api_key},
        headers={
            "Content-Type": "application/json",
            "X-Bunq-Client-Authentication": installation_token
        }
    )
    r.raise_for_status()
    resp = r.json()["Response"]
    session_token = _extract(resp, "Token")["token"]

    user_data = _extract(resp, "UserPerson") or _extract(resp, "UserCompany")
    user_id = user_data["id"]

    return session_token, user_id


def get_headers(session_token):
    return {
        "Content-Type": "application/json",
        "X-Bunq-Client-Authentication": session_token,
        "Cache-Control": "no-cache"
    }


def get_monetary_accounts(session_token, user_id):
    r = requests.get(
        f"{SANDBOX_BASE}/user/{user_id}/monetary-account",
        headers=get_headers(session_token)
    )
    r.raise_for_status()
    accounts = []
    for item in r.json()["Response"]:
        acct = item.get("MonetaryAccountBank") or item.get("MonetaryAccount")
        if acct and acct.get("status") == "ACTIVE":
            alias = next(
                (a["value"] for a in acct.get("alias", []) if a["type"] == "IBAN"),
                None
            )
            accounts.append({
                "id": acct["id"],
                "iban": alias,
                "balance": acct.get("balance", {}).get("value", "0"),
                "currency": acct.get("currency", "EUR")
            })
    return accounts


def get_payments(session_token, user_id, account_id, count=50):
    r = requests.get(
        f"{SANDBOX_BASE}/user/{user_id}/monetary-account/{account_id}/payment",
        params={"count": count},
        headers=get_headers(session_token)
    )
    r.raise_for_status()
    payments = []
    for item in r.json().get("Response", []):
        p = item.get("Payment", {})
        if not p:
            continue
        payments.append({
            "id": p.get("id"),
            "amount": p.get("amount", {}).get("value", "0"),
            "currency": p.get("amount", {}).get("currency", "EUR"),
            "type": p.get("type"),
            "created": p.get("created"),
            "from_iban": p.get("alias", {}).get("value"),
            "from_name": p.get("alias", {}).get("name"),
            "to_iban": p.get("counterparty_alias", {}).get("value"),
            "to_name": p.get("counterparty_alias", {}).get("name"),
        })
    return payments
