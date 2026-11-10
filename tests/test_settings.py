from ai_recruitment_agent.settings import DEFAULT_GEMINI_MODEL, Settings


def test_reads_every_setting():
    env = {
        "GOOGLE_GEMINI_API_KEY": "g", "NOTION_API_KEY": "n", "DEFAULT_NOTION_DB_ID": "db",
        "NOTION_DATA_SOURCE_ID": "ds", "GEMINI_MODEL": "gemini-x",
    }
    s = Settings.load(env, dotenv=False)
    assert (s.gemini_api_key, s.notion_api_key, s.notion_database_id, s.notion_data_source_id, s.gemini_model) == ("g", "n", "db", "ds", "gemini-x")


def test_missing_settings_are_none_and_the_model_has_a_default():
    s = Settings.load({}, dotenv=False)
    assert (s.gemini_api_key, s.notion_api_key, s.notion_database_id, s.notion_data_source_id) == (None, None, None, None)
    assert s.gemini_model == DEFAULT_GEMINI_MODEL == "gemini-3.8-flash"


def test_blank_values_count_as_missing_and_values_are_trimmed():
    s = Settings.load({"GOOGLE_GEMINI_API_KEY": "   ", "NOTION_API_KEY": "  key \n", "GEMINI_MODEL": " "}, dotenv=False)
    assert s.gemini_api_key is None
    assert s.notion_api_key == "key"
    assert s.gemini_model == DEFAULT_GEMINI_MODEL


def test_reads_the_process_environment_by_default(monkeypatch):
    monkeypatch.setenv("NOTION_API_KEY", "from-env")
    assert Settings.load(dotenv=False).notion_api_key == "from-env"


def test_a_dotenv_file_in_the_working_directory_is_loaded_but_never_overrides_the_environment(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text("GOOGLE_GEMINI_API_KEY=from-file\nNOTION_API_KEY=from-file\n")
    monkeypatch.setenv("NOTION_API_KEY", "from-env")
    s = Settings.load()
    assert s.gemini_api_key == "from-file"
    assert s.notion_api_key == "from-env"


def test_a_dotenv_file_is_not_loaded_when_the_environment_is_given(tmp_path):
    import os

    (tmp_path / ".env").write_text("GOOGLE_GEMINI_API_KEY=from-file\n")
    assert Settings.load({}).gemini_api_key is None
    assert "GOOGLE_GEMINI_API_KEY" not in os.environ  # and the process environment was not touched


def test_settings_are_immutable():
    import dataclasses

    import pytest

    with pytest.raises(dataclasses.FrozenInstanceError):
        Settings.load({}, dotenv=False).gemini_model = "x"  # type: ignore[misc]
