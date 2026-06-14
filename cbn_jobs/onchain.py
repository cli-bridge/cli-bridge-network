"""CAW onchain settlement for ERC-8183 jobs (hybrid path).

At job `complete`, transfer testnet SETH to the provider via the CAW transfer
pact (created by runtime/erc8183/make_pact.py). This is the REAL onchain
settlement leg; the offchain job lifecycle is the source of truth (see
cbn_jobs/store.py). Full onchain ERC-8183 contract (createJob/fund/submit as
contract calls) is the documented Phase B upgrade.

CLI: `python -m cbn_jobs.onchain <provider_address> [amount]` — test a settlement.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Pact created by runtime/erc8183/make_pact.py (transfer SETH on SETH chain).
PACT_ID = "10ed93a8-f0a7-4563-b5f3-0862c9a47781"
CHAIN_ID = "SETH"
# The CAW wallet's SETH/EVM address (from `caw onboard` / default_addresses ETH).
SRC_ADDRESS = "0xf01c70d51b4a441e77c553c08975c27b5e4baade"
DEFAULT_AMOUNT = "0.001"


def _caw_base() -> list[str]:
    from cbn_tools.external_cli import _caw
    return _caw(ROOT)


def settle(provider_address: str, amount: str = DEFAULT_AMOUNT, *, pact_id: str = PACT_ID,
           chain_id: str = CHAIN_ID) -> dict:
    """Transfer `amount` SETH to provider_address under the settlement pact."""
    args = [
        "tx", "transfer",
        "--src-address", SRC_ADDRESS,
        "--dst-address", provider_address,
        "--amount", amount,
        "--token-id", chain_id,
        "--chain-id", chain_id,
        "--pact-id", pact_id,
        "--description", "ERC-8183 job settlement (CBN)",
    ]
    r = subprocess.run(_caw_base() + args, capture_output=True, timeout=180)
    out = (r.stdout or b"").decode("utf-8", "replace")
    err = (r.stderr or b"").decode("utf-8", "replace")
    tx_id = ""
    try:
        data = json.loads(out)
        tx_id = (data.get("result") or {}).get("transaction_id") or data.get("transaction_id") or ""
    except Exception:
        pass
    return {
        "ok": r.returncode == 0,
        "exit_code": r.returncode,
        "transaction_id": tx_id,
        "chain_id": chain_id,
        "amount": amount,
        "to": provider_address,
        "pact_id": pact_id,
        "stdout": out[:1200],
        "stderr": err[:800],
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"ok": False, "error": "usage: python -m cbn_jobs.onchain <provider_address> [amount]"}))
        sys.exit(1)
    addr = sys.argv[1]
    amt = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_AMOUNT
    print(json.dumps(settle(addr, amt), ensure_ascii=False))
