import json

from typer.testing import CliRunner

from firstcut import cli
from tests.fakes import FakeWordPressClient, ScriptedChatModel, mcp_wordpress_tools, site_responder


def test_run_prints_progress_and_saves_json(tmp_path, monkeypatch):
    monkeypatch.setattr(
        cli, "get_chat_model", lambda _settings: ScriptedChatModel(respond=site_responder())
    )
    brief = tmp_path / "brief.md"
    brief.write_text("Masa Bakery brief", encoding="utf-8")
    out = tmp_path / "site.json"

    result = CliRunner().invoke(cli.app, ["run", str(brief), "--out", str(out), "--preview"])

    assert result.exit_code == 0, result.output
    assert "plan_sitemap" in result.output
    assert "Masa Bakery" in result.output
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert [page["slug"] for page in saved["pages"]] == ["home", "workshops", "contact"]


def test_run_asks_for_approval_and_publishes(tmp_path, monkeypatch):
    wp = FakeWordPressClient()
    monkeypatch.setattr(
        cli, "get_chat_model", lambda _settings: ScriptedChatModel(respond=site_responder())
    )
    monkeypatch.setattr(cli, "wordpress_tools", lambda _settings: mcp_wordpress_tools(wp))
    brief = tmp_path / "brief.md"
    brief.write_text("Masa Bakery brief", encoding="utf-8")

    result = CliRunner().invoke(cli.app, ["run", str(brief)], input="y\n")

    assert result.exit_code == 0, result.output
    assert "Publish these pages?" in result.output
    assert "published" in result.output
    assert all(page["status"] == "publish" for page in wp.pages.values())
