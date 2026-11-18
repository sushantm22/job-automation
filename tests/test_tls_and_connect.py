"""Fixes from the Copilot onboarding test: certificate errors in VS Code's terminal."""
from __future__ import annotations

import builtins
import ssl
import sys
import types
from urllib.error import HTTPError, URLError

from src import onboarding, onboard_steps
from src.integrations import notion_client
from src.utils import net


def _cert_error() -> URLError:
    return URLError(ssl.SSLCertVerificationError(1, "certificate verify failed: unable to get local issuer certificate"))


def test_certificate_error_is_a_connection_problem_not_a_rejection():
    assert net.could_not_connect(_cert_error()) is True
    assert net.could_not_connect(HTTPError("u", 401, "Unauthorized", {}, None)) is False
    # Certificate errors are not retried by the Notion client (only DNS/refused are).
    assert net.never_reached_server(_cert_error()) is False


def test_key_check_with_certificate_error_says_couldnt_check(monkeypatch):
    def tls_broken(*a, **k):
        raise _cert_error()

    monkeypatch.setattr(onboarding.urllib.request, "urlopen", tls_broken)
    assert onboarding.test_notion_key("ntn_valid_looking_key") is None  # not False ("failed")

    def rejected(*a, **k):
        raise HTTPError("u", 401, "Unauthorized", {}, None)

    monkeypatch.setattr(onboarding.urllib.request, "urlopen", rejected)
    assert onboarding.test_notion_key("ntn_wrong_key") is False


def test_unreachable_message_mentions_certificates_and_key_may_be_fine():
    assert "certificate" in onboard_steps.UNREACHABLE and "may be fine" in onboard_steps.UNREACHABLE


def test_notion_certificate_error_message_has_no_sharing_tip():
    message, sharing_problem = notion_client.explain_notion_error(_cert_error())
    assert "certificate" in message and "not your Notion setup" in message
    assert sharing_problem is False


def test_use_system_trust_store_injects_truststore(monkeypatch):
    calls = []
    fake = types.ModuleType("truststore")
    fake.inject_into_ssl = lambda: calls.append(1)
    monkeypatch.setitem(sys.modules, "truststore", fake)
    assert net.use_system_trust_store() is True and calls == [1]


def test_use_system_trust_store_is_optional(monkeypatch):
    real_import = builtins.__import__

    def no_truststore(name, *a, **k):
        if name == "truststore":
            raise ImportError("not installed")
        return real_import(name, *a, **k)

    monkeypatch.delitem(sys.modules, "truststore", raising=False)
    monkeypatch.setattr(builtins, "__import__", no_truststore)
    assert net.use_system_trust_store() is False
