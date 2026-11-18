from __future__ import annotations

from pathlib import Path

import pytest

import src.config


@pytest.fixture(autouse=True)
def _ignore_developers_local_config(tmp_path_factory, monkeypatch):
    """
    Tests must not depend on the person running them. When code loads the project's real
    config.yaml, hide that developer's personal config.local.yaml (e.g. their own target roles),
    so every test sees the shared defaults. Tests that use their own temporary config are unaffected.
    """
    real_config = src.config.CONFIG_PATH.resolve()
    isolated_local = tmp_path_factory.mktemp("no_local_config") / "config.local.yaml"
    original = src.config.local_config_path

    def local_config_path(config_path: Path = src.config.CONFIG_PATH) -> Path:
        if Path(config_path).resolve() == real_config:
            return isolated_local
        return original(config_path)

    monkeypatch.setattr(src.config, "local_config_path", local_config_path)


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch):
    """
    Tests must never hit real job boards or APIs. Any urllib request that a test hasn't faked
    raises immediately, so an accidental live call fails loudly instead of passing slowly.
    Tests that fake responses patch urlopen themselves, which takes precedence over this.
    """
    import urllib.request

    def blocked(*args, **kwargs):
        raise RuntimeError("Real network access is disabled in tests; patch urlopen or the fetcher.")

    monkeypatch.setattr(urllib.request, "urlopen", blocked)
