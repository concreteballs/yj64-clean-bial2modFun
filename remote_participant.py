"""Explicit placeholder for the future remote participant installed on an administrator's computer.

This module deliberately performs no network connection, command execution, or remote access.
The actual protocol and installation steps will be designed with the administrator.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RemoteParticipantStatus:
    configured: bool = False
    connected: bool = False
    state: str = "placeholder"
    message: str = (
        "Remote participant is not installed or connected. "
        "Administrator-side module and authenticated transport are pending design."
    )


def get_status() -> RemoteParticipantStatus:
    """Return truthful local status without probing or contacting another computer."""
    return RemoteParticipantStatus()


def connect() -> RemoteParticipantStatus:
    """Safe stub: no connection is attempted until the admin protocol is approved."""
    return get_status()
