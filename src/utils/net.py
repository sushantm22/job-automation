"""Small networking helpers shared by the Notion client, key checks and discovery."""
from __future__ import annotations

import socket
import ssl
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


def could_not_connect(err: BaseException) -> bool:
    """
    True when the request failed before any server answered: offline/DNS/refused (see
    never_reached_server) or a TLS certificate problem on this machine. Such a failure says nothing
    about whether an API key is valid, so key checks report "couldn't check", never "failed".
    """
    if isinstance(err, error.HTTPError):
        return False
    reason = getattr(err, "reason", err)
    return never_reached_server(err) or isinstance(reason, ssl.SSLError) or isinstance(err, ssl.SSLError)


def use_system_trust_store() -> bool:
    """
    Verify HTTPS certificates with the operating system's trust store (macOS Keychain, Windows
    certificate store) via `truststore`, instead of OpenSSL's file paths. Those paths are missing on
    some Python installs and can be overridden by a terminal's environment (seen in VS Code /
    Copilot: CERTIFICATE_VERIFY_FAILED). Returns False if truststore isn't installed.
    """
    try:
        import truststore
    except ImportError:
        return False
    truststore.inject_into_ssl()
    return True
