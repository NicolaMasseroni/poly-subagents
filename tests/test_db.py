import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import MagicMock, patch


def test_get_conn_uses_env_vars(monkeypatch):
    monkeypatch.setenv("DB_HOST", "testhost")
    monkeypatch.setenv("DB_PORT", "5433")
    monkeypatch.setenv("DB_NAME", "testdb")
    monkeypatch.setenv("DB_USER", "testuser")
    monkeypatch.setenv("DB_PASSWORD", "testpass")

    with patch("psycopg2.connect") as mock_connect:
        mock_connect.return_value = MagicMock()
        from tools.db import get_conn

        get_conn()
        mock_connect.assert_called_once_with(
            host="testhost",
            port=5433,
            dbname="testdb",
            user="testuser",
            password="testpass",
        )
