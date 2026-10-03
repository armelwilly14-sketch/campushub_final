import os
from unittest.mock import MagicMock

import app.app as app_module


def test_runtime_schema_adds_avatar_column():
    mock_db = MagicMock()
    mock_cursor = MagicMock()
    mock_db.cursor.return_value = mock_cursor
    app_module.get_db_connection = lambda: mock_db

    app_module.ensure_runtime_schema()

    executed_sql = [args[0] for args, _ in mock_cursor.execute.call_args_list]
    assert any("avatar" in sql.lower() and "add column" in sql.lower() for sql in executed_sql)


def test_load_runtime_env_uses_dotenv_when_env_is_blank(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("MISTRAL_API_KEY=test-mistral-key\nAI_PROVIDER=mistral\n", encoding="utf-8")

    monkeypatch.setenv("MISTRAL_API_KEY", "")
    monkeypatch.setenv("AI_PROVIDER", "")
    monkeypatch.setattr(app_module, "APP_DIR", str(tmp_path))

    app_module.load_runtime_env()

    assert os.getenv("MISTRAL_API_KEY") == "test-mistral-key"
    assert os.getenv("AI_PROVIDER") == "mistral"
