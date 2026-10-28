import json

import pytest

from career_radar.cli import main


def test_cli_invalid_budget(monkeypatch):
    monkeypatch.setattr("sys.argv", ["career-radar", "ingest", "--max-requests", "0"])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2


def test_cli_summary(monkeypatch, engine, capsys):
    monkeypatch.setattr("sys.argv", ["career-radar", "ingest", "--test-run"])
    monkeypatch.setattr("career_radar.cli.make_engine", lambda _: engine)

    def run(db, settings):
        assert settings.max_queries == 1
        assert settings.max_requests == 4
        assert settings.verification_budget == 0
        return {"status": "partial"}

    monkeypatch.setattr("career_radar.cli.run_ingestion", run)
    assert main() == 2
    assert json.loads(capsys.readouterr().out)["status"] == "partial"
