from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = ROOT / "python"
sys.path.insert(0, str(PYTHON_ROOT))

from agent_cli_contract import validate_agent_cli_card, validate_run_receipt  # noqa: E402


def main() -> int:
    card = _read_json(ROOT / "fixtures" / "agent-cli-card.valid.json")
    receipt = _read_json(ROOT / "fixtures" / "run-receipt.valid.json")
    card_report = validate_agent_cli_card(card)
    receipt_report = validate_run_receipt(receipt)
    ok = bool(card_report["ok"] and receipt_report["ok"])
    payload = {
        "ok": ok,
        "contract": "agent-cli-contract",
        "card": card_report,
        "receipt": receipt_report,
        "independent_boundary": _check_no_cbn_imports(),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if ok and payload["independent_boundary"]["ok"] else 1


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _check_no_cbn_imports() -> dict[str, object]:
    offenders = []
    for path in (ROOT / "python").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "import cbn" in text or "from cbn" in text:
            offenders.append(str(path.relative_to(ROOT)))
    return {"ok": not offenders, "offenders": offenders}


if __name__ == "__main__":
    raise SystemExit(main())
