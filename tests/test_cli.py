import json

from typer.testing import CliRunner

from firstcut import cli
from tests.fakes import ScriptedChatModel, site_responder


def test_run_prints_progress_and_saves_json(tmp_path, monkeypatch):
    monkeypatch.setattr(
        cli, "get_chat_model", lambda _settings: ScriptedChatModel(respond=site_responder())
    )
    brief = tmp_path / "brief.md"
    brief.write_text("Masa Bakery brief", encoding="utf-8")
    out = tmp_path / "site.json"

    result = CliRunner().invoke(cli.app, ["run", str(brief), "--out", str(out)])

    assert result.exit_code == 0, result.output
    assert "plan_sitemap" in result.output
    assert "Masa Bakery" in result.output
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert [page["slug"] for page in saved["pages"]] == ["home", "workshops", "contact"]
