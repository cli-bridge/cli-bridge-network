"""Compatibility re-export for the core CBN BridgeMessage contract."""

from cbn_core.message import (  # noqa: F401
    BRIDGE_MESSAGE_API_VERSION,
    BridgeMessage,
    bridge_args_from_selectors,
    now_iso,
    validate_bridge_message,
)
from cbn_core.selector import (  # noqa: F401
    bridge_value_to_arg,
    select_bridge_value,
    validate_selector_syntax,
)

__all__ = [
    "BRIDGE_MESSAGE_API_VERSION",
    "BridgeMessage",
    "bridge_args_from_selectors",
    "bridge_value_to_arg",
    "now_iso",
    "select_bridge_value",
    "validate_bridge_message",
    "validate_selector_syntax",
]
