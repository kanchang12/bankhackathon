"""
Sandbox setup — creates a realistic smurfing scenario for demo/testing.
Creates 8 extra sandbox users, then injects payments to simulate a smurf ring.

Run this ONCE before main.py to populate your sandbox with test data.
"""

import requests
import random
import time

SANDBOX_BASE = "https://public-api.sandbox.bunq.com/v1"


def create_sandbox_user():
    """Create a new sandbox person user — returns their API key."""
    r = requests.post(f"{SANDBOX_BASE}/sandbox-user-person")
    r.raise_for_status()
    return r.json()["Response"][0]["ApiKey"]["api_key"]


def quick_session(api_key):
    """Minimal auth flow for a smurf account — returns (session_token, user_id, account_id)."""
    from bunq_auth import setup_session, get_monetary_accounts
    session_token, user_id = setup_session(api_key)
    accounts = get_monetary_accounts(session_token, user_id)
    if not accounts:
        return None, None, None
    return session_token, user_id, accounts[0]["id"], accounts[0]["iban"]


def make_payment(session_token, user_id, account_id,
                  amount, target_iban, description="transfer"):
    """Send a payment from this account to target_iban."""
    from bunq_auth import get_headers
    payload = {
        "amount": {"value": str(round(amount, 2)), "currency": "EUR"},
        "counterparty_alias": {"type": "IBAN", "value": target_iban, "name": "Target"},
        "description": description
    }
    r = requests.post(
        f"{SANDBOX_BASE}/user/{user_id}/monetary-account/{account_id}/payment",
        json=payload,
        headers=get_headers(session_token)
    )
    return r.status_code, r.text


def add_sandbox_funds(session_token, user_id, account_id, amount=5000):
    """Use bunq sandbox topup to add fake money."""
    from bunq_auth import get_headers
    payload = {
        "amount": {"value": str(amount), "currency": "EUR"},
        "description": "sandbox topup"
    }
    r = requests.post(
        f"{SANDBOX_BASE}/user/{user_id}/monetary-account/{account_id}/sandbox-payment-request",
        json=payload,
        headers=get_headers(session_token)
    )
    return r.status_code


def setup_smurf_ring(target_session_token, target_user_id, target_account_id,
                      target_iban, num_smurfs=8):
    """
    Create num_smurfs accounts, give each €5000, 
    then send small amounts to the target (simulating smurfing).
    """
    print(f"\n[SETUP] Creating {num_smurfs}-account smurf ring targeting {target_iban[:12]}...")

    smurf_amounts = [
        random.uniform(420, 499) for _ in range(num_smurfs)
    ]

    results = []
    for i, amount in enumerate(smurf_amounts):
        print(f"  Creating smurf {i+1}/{num_smurfs}...", end=" ")
        try:
            smurf_key = create_sandbox_user()
            time.sleep(0.5)
            session, uid, aid, iban = quick_session(smurf_key)
            if not session:
                print("SKIP (no account)")
                continue
            # Note: sandbox topup may not be available — payments will use existing balance
            status, _ = make_payment(
                session, uid, aid, amount, target_iban,
                description=f"payment {i+1}"
            )
            results.append({"smurf": i+1, "amount": amount, "status": status})
            print(f"€{amount:.2f} → status {status}")
            time.sleep(1)
        except Exception as e:
            print(f"ERROR: {e}")

    print(f"\n[SETUP] Ring complete. {len(results)} payments attempted.")
    return results


if __name__ == "__main__":
    import sys
    sys.path.insert(0, ".")
    from bunq_auth import setup_session, get_monetary_accounts

    API_KEY = "sandbox_70847077b9ce2b996acb68e0c0949e89c98093b5375a95d1a7818592"

    print("[AUTH] Setting up main session...")
    session_token, user_id = setup_session(API_KEY)
    accounts = get_monetary_accounts(session_token, user_id)

    if not accounts:
        print("ERROR: No active accounts found")
        sys.exit(1)

    main_account = accounts[0]
    print(f"[AUTH] Main account: {main_account['iban']} (€{main_account['balance']})")

    setup_smurf_ring(
        target_session_token=session_token,
        target_user_id=user_id,
        target_account_id=main_account["id"],
        target_iban=main_account["iban"],
        num_smurfs=8
    )
