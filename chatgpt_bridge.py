"""Safe placeholder for a future bridge to a supported ChatGPT channel.

This module does not automate the ChatGPT UI, read browser sessions, or transmit
conversation data. A supported transport and explicit consent flow must be selected first.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class BridgeStatus:
    available: bool = False
    connected: bool = False
    state: str = "placeholder"
    message: str = (
        "ChatGPT bridge is not connected. No supported channel/API has been configured; "
        "no chat content has been sent outside this app."
    )


def get_status() -> BridgeStatus:
    return BridgeStatus()
