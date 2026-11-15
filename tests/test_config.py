from src.config import load_settings


def test_load_settings_reads_yaml_and_env(tmp_path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
search:
  keywords: ["python engineer"]
  locations: ["Remote"]
  exclude_keywords: ["intern"]
  min_match_score: 80
limits:
  max_applications_per_day: 12
  min_delay_seconds: 3
  max_delay_seconds: 7
mode:
  default: dry-run
  headless: true
llm:
  max_calls_per_application: 5
  temperature: 0.1
tailoring:
  enabled: false
  cover_letter: true
""".strip(),
        encoding="utf-8",
    )

    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("LLM_MODEL", "openrouter-test-model")

    settings = load_settings(config_path)

    assert settings.search_keywords == ["python engineer"]
    assert settings.locations == ["Remote"]
    assert settings.exclude_keywords == ["intern"]
    assert settings.min_match_score == 80
    assert settings.max_applications_per_day == 12
    assert settings.default_mode == "dry-run"
    assert settings.headless is True
    assert settings.llm_provider == "openrouter"
    assert settings.llm_model == "openrouter-test-model"
    assert settings.tailoring_enabled is False
    assert settings.cover_letter_enabled is True
