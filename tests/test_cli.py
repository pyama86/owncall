"""Tests for CLI config directory loading."""

import textwrap
from unittest.mock import AsyncMock, patch

import pytest

from owncall.cli import main

_MINIMAL_CONFIG = textwrap.dedent("""
    slack:
      app_token: "xapp-test"
      bot_token: "xoxb-test"
""")


class TestCliConfigDirectory:
    def test_directory_runs_bots_with_all_yml_files(self, tmp_path, monkeypatch):
        (tmp_path / "sre.yml").write_text(_MINIMAL_CONFIG)
        (tmp_path / "backend.yml").write_text(_MINIMAL_CONFIG)
        (tmp_path / "not_a_config.txt").write_text("ignored")

        monkeypatch.setattr("sys.argv", ["owncall", "-c", str(tmp_path)])

        with patch("owncall.app.run_bots", new_callable=AsyncMock) as mock_run_bots:
            with patch("asyncio.run"):
                main()
            # run_bots must be called once its coroutine is awaited via asyncio.run
            # Verify 2 configs were loaded (sre + backend, txt ignored)
            mock_run_bots.assert_called_once()
            configs = mock_run_bots.call_args[0][0]
            assert len(configs) == 2

    def test_empty_directory_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr("sys.argv", ["owncall", "-c", str(tmp_path)])
        with pytest.raises(SystemExit, match="No .yml/.yaml files found"):
            main()

    def test_single_file_runs_single_bot(self, tmp_path, monkeypatch):
        config_file = tmp_path / "config.yml"
        config_file.write_text(_MINIMAL_CONFIG)

        monkeypatch.setattr("sys.argv", ["owncall", "-c", str(config_file)])

        with patch("owncall.app.run_bot", new_callable=AsyncMock) as mock_run_bot:
            with patch("asyncio.run"):
                main()
            mock_run_bot.assert_called_once()
