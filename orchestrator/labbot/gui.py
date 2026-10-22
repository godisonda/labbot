"""Графическая (веб) оболочка LabBot.

Запуск:
    make gui
    python -m orchestrator.labbot.gui [--port 8765] [--no-browser] [--root PATH]

Открывает локальный интерфейс на 127.0.0.1: выбор работы, загрузка задания и
образца, ввод ФИО, запуск генерации с живым логом, просмотр результатов.
Сервер работает только на localhost и не требует интернета (кроме самого API).
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
import webbrowser
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, quote, unquote, urlparse

from .prompts import DEFAULT_PROMPTS, PROMPT_LABELS, PROMPT_PLACEHOLDERS
from .settings import (
    api_key as settings_api_key,
    env_path,
    load_settings,
    mask_key,
    profile_from_env,
    project_root,
    save_settings,
    settings_path,
    write_env_values,
)

try:
    from .extract import find_lab_documents
except ImportError:  # pragma: no cover - на случай запуска без зависимостей
    find_lab_documents = None

def _web_dir() -> Path:
    base = getattr(sys, "_MEIPASS", None)
    if base:
        candidate = Path(base) / "web"
        if candidate.is_dir():
            return candidate
    return Path(__file__).resolve().parent / "web"


WEB_DIR = _web_dir()
STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "application/javascript; charset=utf-8"),
}

DOC_EXTENSIONS = {".docx", ".pdf", ".txt", ".md"}
ARTIFACT_NAMES = {"report.docx", "main.docx", "main.pdf", "report.pdf", "notes.txt"}
FROM_STAGES = ("extract", "outline", "code", "scripts", "sections", "assemble")
MAX_UPLOAD = 100 * 1024 * 1024


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass
class Run:
    id: str
    proc: subprocess.Popen
    cmd: List[str]
    lines: List[str] = field(default_factory=list)
    done: bool = False
    returncode: Optional[int] = None
    started: float = field(default_factory=time.time)
    lock: threading.Lock = field(default_factory=threading.Lock)


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _safe_lab_name(raw: str) -> str:
    """Имя папки работы: буквы, цифры, пробелы, дефис. Без путей и спецсимволов."""
    name = str(raw or "").replace("\\", "/").split("/")[-1].strip()
    name = re.sub(r'[\x00-\x1f<>:"/\\|?*]', "", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    name = name.lstrip(".")
    if not name or name in (".", ".."):
        raise ApiError(400, "Некорректное название работы")
    return name[:80].rstrip()


def _safe_filename(raw: str) -> str:
    name = Path(unquote(raw or "")).name.strip()
    name = re.sub(r'[\x00-\x1f<>:"/\\|?*]', "", name)
    name = name.strip(". ")
    if not name or name in (".", ".."):
        raise ApiError(400, "Некорректное имя файла")
    return name[:180]


def _fmt_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


class App:
    """Состояние оболочки: список работ, профиль, запущенные процессы."""

    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.labs = self.root / "labs"
        self.labs.mkdir(parents=True, exist_ok=True)
        self.runs: Dict[str, Run] = {}
        self.lock = threading.Lock()
        self.active_run_id: Optional[str] = None

    # --- поиск файлов -----------------------------------------------------

    def _documents(self, lab: Path) -> Tuple[Optional[Path], List[Path]]:
        if find_lab_documents is not None:
            return find_lab_documents(lab)
        docs = [
            p for p in sorted(lab.iterdir())
            if p.is_file() and p.suffix.lower() in DOC_EXTENSIONS
            and not p.name.startswith("~$") and p.name.lower() not in ARTIFACT_NAMES
        ]
        return (docs[0] if docs else None), []

    def _lab(self, value: Any) -> Path:
        name = Path(str(value or "")).name
        if not name:
            raise ApiError(400, "Не указана работа")
        lab = (self.labs / name).resolve()
        if lab.parent != self.labs.resolve() or not lab.is_dir():
            raise ApiError(404, "Работа не найдена")
        return lab

    # --- данные для интерфейса -------------------------------------------

    def _api_key_present(self) -> bool:
        env_file = self.root / ".env"
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.strip().startswith("DEEPSEEK_API_KEY="):
                    value = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if len(value) > 10 and "вставьте" not in value:
                        return True
        return bool(os.getenv("DEEPSEEK_API_KEY"))

    def profile_dict(self) -> Dict[str, str]:
        return profile_from_env(self.root)

    def _files(self, lab: Path) -> List[Dict[str, Any]]:
        candidates = [
            "build/main.pdf", "reports/main.pdf", "reports/report.docx",
            "build/report.docx", "src/main.cpp", "src/main.py", "flowchart.png",
        ]
        candidates += [p.name for p in sorted(lab.glob("fig*.png"))]
        seen = set()
        result = []
        for rel in candidates:
            if rel in seen:
                continue
            seen.add(rel)
            path = lab / rel
            if not path.is_file():
                continue
            result.append({
                "path": rel,
                "name": path.name,
                "size": path.stat().st_size,
                "kind": path.suffix.lower().lstrip("."),
            })
        return result

    def lab_summary(self, lab: Path) -> Dict[str, Any]:
        main, refs = self._documents(lab)
        state = _read_json(lab / "build" / "state.json").get("completed_steps", {}) or {}
        outline = _read_json(lab / "build" / "outline.json")
        meta = outline.get("meta", {}) if isinstance(outline, dict) else {}
        pdf = lab / "build" / "main.pdf"
        files = self._files(lab)

        if main is None:
            status = "empty"
        elif state.get("assemble") and pdf.exists():
            status = "done"
        elif state:
            status = "partial"
        else:
            status = "ready"

        known = ("extract", "outline", "code", "scripts", "sections", "assemble")
        done = sum(1 for step in known if state.get(step))
        return {
            "id": lab.name,
            "task": main.name if main else None,
            "refs": [p.name for p in refs],
            "status": status,
            "steps": state,
            "progress": round(done / len(known) * 100),
            "meta": {
                "number": meta.get("number", ""),
                "title": meta.get("title", ""),
                "work_type": meta.get("work_type", ""),
                "discipline": meta.get("discipline", ""),
                "department": meta.get("department", ""),
            },
            "outputs": {item["path"]: item["name"] for item in files},
            "mtime": max([_fmt_mtime(lab)] + [_fmt_mtime(p) for p in lab.iterdir()]),
            "files": files,
        }

    def state(self) -> Dict[str, Any]:
        labs = [
            self.lab_summary(path)
            for path in sorted(self.labs.iterdir())
            if path.is_dir() and not path.name.startswith(".")
        ]
        return {
            "project": str(self.root),
            "labs": labs,
            "profile": self.profile_dict(),
            "python": sys.executable,
            "has_api_key": self._api_key_present(),
            "from_stages": list(FROM_STAGES),
        }

    def lab_details(self, name: str) -> Dict[str, Any]:
        lab = self._lab(name)
        data = self.lab_summary(lab)
        outline = _read_json(lab / "build" / "outline.json")
        meta = outline.get("meta", {}) if isinstance(outline, dict) else {}
        data["variant_summary"] = str(meta.get("variant_summary", ""))[:800]
        data["profile"] = self.profile_dict()
        return data

    # --- настройки --------------------------------------------------------

    def settings_payload(self) -> Dict[str, Any]:
        data = load_settings(self.root)
        key = settings_api_key(self.root)
        return {
            "llm": data["llm"],
            "report": data["report"],
            "prompts": data["prompts"],
            "prompt_defaults": dict(DEFAULT_PROMPTS),
            "prompt_labels": dict(PROMPT_LABELS),
            "prompt_placeholders": dict(PROMPT_PLACEHOLDERS),
            "api_key_masked": mask_key(key),
            "api_key_set": bool(key),
            "profile": profile_from_env(self.root),
            "settings_file": str(settings_path(self.root)),
            "env_file": str(env_path(self.root)),
        }

    def save_settings_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        current = load_settings(self.root)
        llm = payload.get("llm") if isinstance(payload.get("llm"), dict) else current["llm"]
        report = payload.get("report") if isinstance(payload.get("report"), dict) else current["report"]

        prompts = dict(current["prompts"])
        incoming = payload.get("prompts")
        if isinstance(incoming, dict):
            prompts.update({k: v for k, v in incoming.items() if isinstance(v, str)})

        save_settings({"llm": llm, "report": report, "prompts": prompts}, self.root)

        key = str(payload.get("api_key") or "").strip()
        if key and "…" not in key and "•" not in key:
            write_env_values({"DEEPSEEK_API_KEY": key}, self.root)

        profile = payload.get("profile") if isinstance(payload.get("profile"), dict) else {}
        mapping = {
            "student": "STUDENT", "group": "GROUP", "teacher": "TEACHER",
            "faculty": "FACULTY", "department": "DEPARTMENT",
        }
        env_values = {
            env_key: str(profile[field]).strip()
            for field, env_key in mapping.items()
            if field in profile
        }
        if env_values:
            write_env_values(env_values, self.root)

        return self.settings_payload()

    def reset_prompt(self, name: str) -> Dict[str, Any]:
        if name not in DEFAULT_PROMPTS:
            raise ApiError(400, "Неизвестный промпт")
        data = load_settings(self.root)
        prompts = dict(data["prompts"])
        prompts[name] = DEFAULT_PROMPTS[name]
        save_settings({"llm": data["llm"], "report": data["report"], "prompts": prompts}, self.root)
        return self.settings_payload()

    def test_api_key(self, key: Optional[str] = None) -> Dict[str, Any]:
        data = load_settings(self.root)
        value = (key or settings_api_key(self.root)).strip()
        if not value:
            raise ApiError(400, "API-ключ не задан")
        url = data["llm"]["base_url"].rstrip("/") + "/models"
        request = urllib.request.Request(url, headers={"Authorization": f"Bearer {value}"})
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return {"ok": True, "status": response.status}
        except urllib.error.HTTPError as exc:
            raise ApiError(400, f"API ответил HTTP {exc.code}")
        except Exception as exc:  # сеть, DNS, таймаут
            raise ApiError(400, f"Не удалось подключиться: {exc}")

    # --- действия ---------------------------------------------------------

    def _base_command(self) -> List[str]:
        """В упакованном приложении запускаем сами себя с ключом --run-cli."""
        if getattr(sys, "frozen", False):
            return [sys.executable, "--run-cli"]
        return [sys.executable, "-m", "orchestrator.labbot.cli"]

    def build_command(self, payload: Dict[str, Any]) -> List[str]:
        lab = self._lab(payload.get("lab"))
        mode = str(payload.get("mode") or "report").lower()
        cmd = self._base_command()
        if mode in ("pdf", "docx", "build"):
            return cmd + [mode, str(lab)]

        cmd += ["report", str(lab)]
        for flag, key in (
            ("--variant", "variant"),
            ("--student", "student"),
            ("--group", "group"),
            ("--teacher", "teacher"),
            ("--faculty", "faculty"),
            ("--department", "department"),
            ("--from-stage", "from_stage"),
        ):
            value = str(payload.get(key) or "").strip()
            if value:
                cmd.extend([flag, value])
        if payload.get("remember"):
            cmd.append("--remember")
        return cmd

    def start_run(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        mode = str(payload.get("mode") or "report").lower()
        lab = self._lab(payload.get("lab"))

        if mode == "report":
            main, _ = self._documents(lab)
            if main is None:
                raise ApiError(
                    400,
                    "В папке работы нет задания. Загрузите методичку или ТЗ "
                    "(PDF/DOCX/TXT) в блоке «Документы».",
                )
            if not self._api_key_present():
                raise ApiError(400, "Не найден DEEPSEEK_API_KEY в .env — генерация невозможна.")

        with self.lock:
            if self.active_run_id:
                raise ApiError(409, "Уже идёт генерация. Дождитесь окончания или остановите её.")

        cmd = self.build_command(payload)
        env = dict(os.environ)
        env["PYTHONUNBUFFERED"] = "1"
        env["LABBOT_ROOT"] = str(self.root)
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.Popen(
            cmd,
            cwd=str(self.root),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env,
        )
        run = Run(id=uuid.uuid4().hex[:8], proc=proc, cmd=cmd)
        with self.lock:
            self.runs[run.id] = run
            self.active_run_id = run.id
            for old_id in list(self.runs)[:-10]:
                self.runs.pop(old_id, None)
        threading.Thread(target=self._pump, args=(run,), daemon=True).start()
        return {"id": run.id, "cmd": cmd}

    def _pump(self, run: Run) -> None:
        assert run.proc.stdout is not None
        try:
            for line in run.proc.stdout:
                with run.lock:
                    run.lines.append(line.rstrip("\n"))
        finally:
            code = run.proc.wait()
            with run.lock:
                run.returncode = code
                run.done = True
            with self.lock:
                if self.active_run_id == run.id:
                    self.active_run_id = None

    def cancel_run(self, run_id: str) -> Dict[str, Any]:
        run = self.runs.get(run_id)
        if not run:
            raise ApiError(404, "Запуск не найден")
        if run.done:
            return {"ok": True, "already": True}
        run.proc.terminate()

        def _kill_later() -> None:
            time.sleep(4)
            if run.proc.poll() is None:
                run.proc.kill()

        threading.Thread(target=_kill_later, daemon=True).start()
        return {"ok": True}

    def save_upload(self, lab_name: str, kind: str, filename: str, data: bytes) -> Dict[str, Any]:
        lab = self._lab(lab_name)
        if kind not in ("task", "refs"):
            raise ApiError(400, "Неизвестный тип загрузки")
        if len(data) > MAX_UPLOAD:
            raise ApiError(413, "Файл больше 100 МБ")
        if not data:
            raise ApiError(400, "Пустой файл")

        name = _safe_filename(filename)
        if kind == "task":
            if name.lower() in ARTIFACT_NAMES:
                raise ApiError(400, "Такой файл создаётся генерацией — выберите другое имя")
            target = lab / name
        else:
            refs_dir = lab / "refs"
            refs_dir.mkdir(exist_ok=True)
            target = refs_dir / name

        target.write_bytes(data)
        return {"ok": True, "name": target.name, "where": str(target.parent.relative_to(lab))}

    def file_path(self, lab_name: str, rel: str) -> Path:
        lab = self._lab(lab_name)
        rel = unquote(rel or "")
        if not rel:
            raise ApiError(400, "Не указан файл")
        target = (lab / rel).resolve()
        if lab not in target.parents or not target.is_file():
            raise ApiError(404, "Файл не найден")
        return target

    def create_lab(self, value: Any) -> Dict[str, Any]:
        raw = str(value or "").strip()
        if not raw:
            raise ApiError(400, "Укажите название работы")
        # «04» → lab_04, «Курсовая по сетям» → labs/Курсовая по сетям
        name = f"lab_{int(raw):02d}" if raw.isdigit() else _safe_lab_name(raw)
        lab = self.labs / name
        if lab.exists():
            raise ApiError(409, f"«{name}» уже существует")
        for sub in ("build", "reports", "scripts", "src", "refs"):
            (lab / sub).mkdir(parents=True, exist_ok=True)
        return {"ok": True, "id": name}

    def delete_lab(self, lab_name: str) -> Dict[str, Any]:
        lab = self._lab(lab_name)
        with self.lock:
            if self.active_run_id:
                raise ApiError(409, "Идёт генерация — остановите её перед удалением")
        shutil.rmtree(lab)
        return {"ok": True, "id": lab.name}

    def clean_lab(self, lab_name: str) -> Dict[str, Any]:
        lab = self._lab(lab_name)
        for sub in ("build", "scripts", "src"):
            target = lab / sub
            if target.is_dir():
                for child in target.iterdir():
                    if child.is_dir():
                        shutil.rmtree(child)
                    else:
                        child.unlink()
        return {"ok": True}

    def reveal(self, lab_name: str) -> Dict[str, Any]:
        lab = self._lab(lab_name)
        if sys.platform == "darwin":
            opener = ["open"]
        elif sys.platform.startswith("win"):
            opener = ["explorer"]
        elif sys.platform.startswith("linux"):
            opener = ["xdg-open"]
        else:
            raise ApiError(400, "Открытие папки не поддерживается")
        subprocess.Popen(opener + [str(lab)])
        return {"ok": True}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args: Any) -> None:  # тише в консоли
        pass

    @property
    def app(self) -> App:
        return self.server.app  # type: ignore[attr-defined]

    # --- helpers ----------------------------------------------------------

    def _json(self, data: Any, status: int = HTTPStatus.OK) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, exc: ApiError) -> None:
        self._json({"error": exc.message}, exc.status)

    def _body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return b""
        return self.rfile.read(length)

    def _payload(self) -> Dict[str, Any]:
        body = self._body()
        if not body:
            return {}
        try:
            data = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ApiError(400, "Некорректный JSON")
        if not isinstance(data, dict):
            raise ApiError(400, "Ожидался JSON-объект")
        return data

    # --- GET --------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            if parsed.path in STATIC_FILES:
                filename, mime = STATIC_FILES[parsed.path]
                return self._static(WEB_DIR / filename, mime)
            if parsed.path == "/api/state":
                return self._json(self.app.state())
            if parsed.path == "/api/settings":
                return self._json(self.app.settings_payload())
            if parsed.path == "/api/lab":
                name = parse_qs(parsed.query).get("lab", [""])[0]
                return self._json(self.app.lab_details(name))
            if parsed.path.startswith("/api/log/"):
                return self._sse(parsed.path.rsplit("/", 1)[-1])
            if parsed.path == "/api/file":
                qs = parse_qs(parsed.query)
                path = self.app.file_path(qs.get("lab", [""])[0], qs.get("path", [""])[0])
                return self._static(path, mimetypes.guess_type(path.name)[0] or "application/octet-stream", download=qs.get("download", ["0"])[0] == "1")
            raise ApiError(404, "Не найдено")
        except ApiError as exc:
            self._error(exc)
        except Exception as exc:  # pragma: no cover - защита от падений
            self._json({"error": f"Внутренняя ошибка: {exc}"}, 500)

    def _static(self, path: Path, mime: str, download: bool = False) -> None:
        try:
            data = path.read_bytes()
        except OSError:
            raise ApiError(404, "Файл не найден")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        disposition = "attachment" if download else "inline"
        self.send_header(
            "Content-Disposition", f"{disposition}; filename*=UTF-8''{quote(path.name)}"
        )
        self.end_headers()
        self.wfile.write(data)

    def _sse(self, run_id: str) -> None:
        run = self.app.runs.get(run_id)
        if not run:
            raise ApiError(404, "Запуск не найден")

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

        sent = 0
        try:
            while True:
                with run.lock:
                    pending = run.lines[sent:]
                    sent += len(pending)
                    done = run.done
                    code = run.returncode
                for line in pending:
                    payload = json.dumps({"line": line}, ensure_ascii=False)
                    self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                if pending:
                    self.wfile.flush()
                if done:
                    self.wfile.write(
                        f"event: done\ndata: {json.dumps({'returncode': code})}\n\n".encode("utf-8")
                    )
                    self.wfile.flush()
                    return
                self.wfile.write(b": ping\n\n")
                self.wfile.flush()
                time.sleep(0.35)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True

    # --- POST -------------------------------------------------------------

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        try:
            if parsed.path == "/api/upload":
                kind = qs.get("kind", [""])[0]
                name = qs.get("name", [""])[0]
                lab = qs.get("lab", [""])[0]
                result = self.app.save_upload(lab, kind, name, self._body())
                return self._json(result)
            if parsed.path == "/api/settings":
                return self._json(self.app.save_settings_payload(self._payload()))
            if parsed.path == "/api/settings/reset":
                return self._json(self.app.reset_prompt(str(self._payload().get("name") or "")))
            if parsed.path == "/api/settings/test":
                return self._json(self.app.test_api_key(self._payload().get("api_key")))
            if parsed.path == "/api/run":
                return self._json(self.app.start_run(self._payload()))
            if parsed.path == "/api/cancel":
                run_id = str(self._payload().get("id") or "")
                return self._json(self.app.cancel_run(run_id))
            if parsed.path == "/api/new":
                payload = self._payload()
                return self._json(self.app.create_lab(payload.get("name") or payload.get("number")))
            if parsed.path == "/api/delete":
                return self._json(self.app.delete_lab(str(self._payload().get("lab") or "")))
            if parsed.path == "/api/clean":
                return self._json(self.app.clean_lab(str(self._payload().get("lab") or "")))
            if parsed.path == "/api/reveal":
                return self._json(self.app.reveal(str(self._payload().get("lab") or "")))
            raise ApiError(404, "Не найдено")
        except ApiError as exc:
            self._error(exc)
        except Exception as exc:  # pragma: no cover
            self._json({"error": f"Внутренняя ошибка: {exc}"}, 500)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def create_server(root: Path, host: str = "127.0.0.1", port: int = 0) -> Server:
    httpd = Server((host, port), Handler)
    httpd.app = App(root)  # type: ignore[attr-defined]
    return httpd


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="LabBot — графическая оболочка")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--root", type=Path, default=project_root())
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)

    root = args.root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    (root / "labs").mkdir(exist_ok=True)

    port = args.port
    httpd = None
    for candidate in range(port, port + 20):
        try:
            httpd = create_server(root, args.host, candidate)
            port = candidate
            break
        except OSError:
            continue
    if httpd is None:
        print(f"Не удалось занять порт {args.port}–{args.port + 19}", file=sys.stderr)
        return 2

    url = f"http://{args.host}:{port}/"
    print(f"LabBot GUI: {url}", flush=True)
    print(f"Проект: {root}", flush=True)
    print("Ctrl+C — остановить сервер", flush=True)

    if not args.no_browser:
        def _open() -> None:
            try:
                webbrowser.open(url)
            except Exception:
                pass

        threading.Timer(0.6, _open).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nОстановлено")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
