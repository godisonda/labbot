import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

from orchestrator.labbot.gui import App, create_server


@pytest.fixture()
def project(tmp_path):
    lab = tmp_path / "labs" / "lab_01"
    (lab / "refs").mkdir(parents=True)
    (lab / "build").mkdir()
    (lab / "Задание.txt").write_text("задание", encoding="utf-8")
    (lab / "refs" / "образец.txt").write_text("образец", encoding="utf-8")
    (lab / "build" / "main.pdf").write_bytes(b"%PDF-1.4 test")
    (tmp_path / "labs" / "lab_02").mkdir()
    (tmp_path / ".env").write_text(
        "STUDENT=Иванов И.И.\nGROUP=ГР-1\nDEEPSEEK_API_KEY=test-key-0000000000\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture()
def server(project):
    httpd = create_server(project, port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    yield base
    httpd.shutdown()
    httpd.server_close()


def get(url):
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def post(url, payload=None, raw=None, headers=None):
    data = raw if raw is not None else json.dumps(payload or {}).encode("utf-8")
    request_headers = {"Content-Type": "application/json"} if raw is None else {}
    request_headers.update(headers or {})
    request = urllib.request.Request(url, data=data, method="POST", headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def json_body(raw: bytes):
    return json.loads(raw.decode("utf-8"))


# --- страница и статика -----------------------------------------------------

def test_index_page(server):
    status, body = get(f"{server}/")
    assert status == 200
    assert "LabBot" in body.decode("utf-8")


def test_static_assets(server):
    for name, marker in (("style.css", "--accent"), ("app.js", "startRun")):
        status, body = get(f"{server}/{name}")
        assert status == 200
        assert marker in body.decode("utf-8")


# --- состояние --------------------------------------------------------------

def test_state_lists_labs_and_profile(server):
    status, body = get(f"{server}/api/state")
    assert status == 200
    data = json_body(body)
    assert [lab["id"] for lab in data["labs"]] == ["lab_01", "lab_02"]
    assert data["profile"]["student"] == "Иванов И.И."
    assert data["has_api_key"] is True


def test_lab_details(server):
    status, body = get(f"{server}/api/lab?lab=lab_01")
    assert status == 200
    data = json_body(body)
    assert data["task"] == "Задание.txt"
    assert data["refs"] == ["образец.txt"]
    assert "build/main.pdf" in data["outputs"]
    assert data["status"] in ("ready", "partial", "done")


def test_lab_details_unknown(server):
    status, _ = get(f"{server}/api/lab?lab=nope")
    assert status == 404


# --- файлы ------------------------------------------------------------------

def test_file_served(server):
    status, body = get(f"{server}/api/file?lab=lab_01&path=build/main.pdf")
    assert status == 200
    assert body.startswith(b"%PDF")


def test_file_traversal_blocked(server):
    status, _ = get(f"{server}/api/file?lab=lab_01&path=../../.env")
    assert status == 404


# --- загрузка ---------------------------------------------------------------

def test_upload_reference(server, project):
    name = urllib.parse.quote("пример.docx")
    status, body = post(f"{server}/api/upload?lab=lab_01&kind=refs&name={name}", raw=b"docx-bytes")
    assert status == 200
    assert json_body(body)["name"] == "пример.docx"
    assert (project / "labs" / "lab_01" / "refs" / "пример.docx").read_bytes() == b"docx-bytes"


def test_upload_traversal_stays_inside_lab(server, project):
    status, body = post(f"{server}/api/upload?lab=lab_01&kind=task&name=../../evil.txt", raw=b"x")
    assert status == 200
    assert json_body(body)["name"] == "evil.txt"
    assert (project / "labs" / "lab_01" / "evil.txt").exists()
    assert not (project / "evil.txt").exists()
    assert not (project / "labs" / "evil.txt").exists()


def test_upload_rejects_empty_body(server):
    status, _ = post(f"{server}/api/upload?lab=lab_01&kind=refs&name=a.txt", raw=b"")
    assert status == 400


# --- работы -----------------------------------------------------------------

def test_create_lab(server, project):
    status, body = post(f"{server}/api/new", {"number": "42"})
    assert status == 200
    assert json_body(body)["id"] == "lab_42"
    for sub in ("build", "reports", "scripts", "src", "refs"):
        assert (project / "labs" / "lab_42" / sub).is_dir()


def test_create_duplicate_lab(server):
    status, _ = post(f"{server}/api/new", {"number": "01"})
    assert status == 409


def test_clean_lab(server, project):
    marker = project / "labs" / "lab_01" / "build" / "main.pdf"
    assert marker.exists()
    status, _ = post(f"{server}/api/clean", {"lab": "lab_01"})
    assert status == 200
    assert not marker.exists()
    assert (project / "labs" / "lab_01" / "Задание.txt").exists()


# --- запуск -----------------------------------------------------------------

def test_run_requires_documents(server):
    status, body = post(f"{server}/api/run", {"lab": "lab_02", "mode": "report"})
    assert status == 400
    assert "нет задания" in json_body(body)["error"]


def test_build_command_report(project):
    app = App(project)
    cmd = app.build_command({
        "lab": "lab_01",
        "mode": "report",
        "variant": "7",
        "student": "Смирнов С.С.",
        "teacher": "Сидоров С.С.",
        "remember": True,
        "from_stage": "sections",
    })
    assert cmd[:3] == [cmd[0], "-m", "orchestrator.labbot.cli"]
    assert "report" in cmd
    assert cmd[cmd.index("--variant") + 1] == "7"
    assert cmd[cmd.index("--student") + 1] == "Смирнов С.С."
    assert cmd[cmd.index("--from-stage") + 1] == "sections"
    assert "--remember" in cmd


def test_build_command_offline(project):
    app = App(project)
    cmd = app.build_command({"lab": "lab_01", "mode": "pdf"})
    assert cmd[-2:] == ["pdf", str(project / "labs" / "lab_01")]


def test_log_unknown_run(server):
    status, _ = get(f"{server}/api/log/deadbeef")
    assert status == 404


# --- настройки --------------------------------------------------------------

def test_settings_endpoint(server):
    status, body = get(f"{server}/api/settings")
    assert status == 200
    data = json_body(body)
    assert len(data["prompts"]) == 7
    assert "system" in data["prompt_labels"]
    assert data["api_key_masked"].startswith("test-")
    assert data["api_key_set"] is True


def test_settings_save_writes_files(server, project):
    status, body = post(f"{server}/api/settings", {
        "llm": {"model": "deepseek-reasoner", "temperature": 0.6},
        "report": {"year": "2027"},
        "prompts": {"system": "НОВЫЙ ПРОМПТ"},
        "api_key": "test-key-1234567890",
        "profile": {"student": "Новый Н.Н.", "teacher": "Препод П.П."},
    })
    assert status == 200
    data = json_body(body)
    assert data["llm"]["model"] == "deepseek-reasoner"
    assert data["prompts"]["system"] == "НОВЫЙ ПРОМПТ"
    assert data["profile"]["student"] == "Новый Н.Н."

    settings = json.loads((project / "settings.json").read_text(encoding="utf-8"))
    assert settings["llm"]["temperature"] == 0.6
    assert settings["llm"]["model"] == "deepseek-reasoner"

    env = (project / ".env").read_text(encoding="utf-8")
    assert "test-key-1234567890" in env
    assert "STUDENT=Новый Н.Н." in env


def test_settings_reset_prompt(server):
    post(f"{server}/api/settings", {"prompts": {"system": "ВРЕМЕННЫЙ"}})
    status, body = post(f"{server}/api/settings/reset", {"name": "system"})
    assert status == 200
    assert json_body(body)["prompts"]["system"].startswith("Ты — ведущий профессор")


def test_settings_reset_unknown_prompt(server):
    status, _ = post(f"{server}/api/settings/reset", {"name": "nope"})
    assert status == 400


def test_build_command_inside_frozen_app(project, monkeypatch):
    import orchestrator.labbot.gui as gui

    monkeypatch.setattr(gui.sys, "frozen", True, raising=False)
    cmd = App(project).build_command({"lab": "lab_01", "mode": "report"})
    assert cmd[1] == "--run-cli"
    assert cmd[2] == "report"


def test_create_lab_by_name(server, project):
    name = "Курсовая по сетям"
    status, body = post(f"{server}/api/new", {"name": name})
    assert status == 200
    assert json_body(body)["id"] == name
    for sub in ("build", "reports", "scripts", "src", "refs"):
        assert (project / "labs" / name / sub).is_dir()


def test_create_lab_name_traversal(server, project):
    status, body = post(f"{server}/api/new", {"name": "../../evil"})
    assert status == 200
    assert json_body(body)["id"] == "evil"
    assert (project / "labs" / "evil").is_dir()
    assert not (project / "evil").exists()


def test_create_lab_empty_name(server):
    status, _ = post(f"{server}/api/new", {"name": "   "})
    assert status == 400


def test_named_lab_is_listed_and_served(server, project):
    post(f"{server}/api/new", {"name": "Зачёт по физике"})
    status, body = get(f"{server}/api/state")
    assert status == 200
    assert "Зачёт по физике" in [lab["id"] for lab in json_body(body)["labs"]]

    encoded = urllib.parse.quote("Зачёт по физике")
    status, body = get(f"{server}/api/lab?lab={encoded}")
    assert status == 200
    assert json_body(body)["id"] == "Зачёт по физике"


def test_delete_lab(server, project):
    post(f"{server}/api/new", {"name": "Временная работа"})
    assert (project / "labs" / "Временная работа").is_dir()

    status, body = post(f"{server}/api/delete", {"lab": "Временная работа"})
    assert status == 200
    assert json_body(body)["id"] == "Временная работа"
    assert not (project / "labs" / "Временная работа").exists()


def test_delete_missing_lab(server):
    status, _ = post(f"{server}/api/delete", {"lab": "nope"})
    assert status == 404


def test_delete_traversal_blocked(server, project):
    status, _ = post(f"{server}/api/delete", {"lab": "../../etc"})
    assert status == 404
    assert (project / "labs").is_dir()


def test_settings_provider_roundtrip(server, project):
    status, body = post(f"{server}/api/settings", {
        "llm": {
            "provider": "openrouter",
            "base_url": "https://openrouter.ai/api/v1",
            "model": "openai/gpt-4o-mini",
        },
    })
    assert status == 200
    data = json_body(body)
    assert data["llm"]["provider"] == "openrouter"
    assert data["llm"]["model"] == "openai/gpt-4o-mini"

    saved = json.loads((project / "settings.json").read_text(encoding="utf-8"))
    assert saved["llm"]["provider"] == "openrouter"
