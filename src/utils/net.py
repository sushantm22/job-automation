"""Small networking helpers shared by the Notion client, key checks and discovery."""
from __future__ import annotations

import socket
from urllib import error


def never_reached_server(err: BaseException) -> bool:
    """
    True only when a request certainly never left this machine: the server name couldn't be resolved
    (no internet, DNS down, or an AI tool's sandbox blocking network) or the connection was refused.
    Such a request is safe to retry, and its failure says nothing about keys, pages or settings.
    """
    if isinstance(err, error.HTTPError):
        return False
    reason = getattr(err, "reason", err)
    return isinstance(reason, (socket.gaierror, ConnectionRefusedError))
