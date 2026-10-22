"""Настройки LabBot: LLM, промпты и данные отчёта.

* `settings.json` в корне проекта — модель, адрес API, лимиты, тексты промптов;
* `.env` — секреты (DEEPSEEK_API_KEY) и профиль исполнителя.

Все значения имеют разумные значения по умолчанию, поэтому отсутствие файла
настроек ничего не ломает.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from .prompts import DEFAULT_PROMPTS, merge_prompts

PROVIDERS = ("deepseek", "openai", "openrouter", "ollama", "custom")

DEFAULT_LLM: Dict[str, Any] = {
    "provider": "deepseek",
    "model": "deepseek-chat",
    "base_url": "https://api.deepseek.com",
    "temperature": 0.2,
    "max_tokens": 8192,
    "timeout": 180,
    "max_retries": 4,
    "max_cost_limit_usd": 1.0,
}

DEFAULT_REPORT: Dict[str, Any] = {
    "year": "",
}

ENV_PROFILE_KEYS = ("STUDENT", "GROUP", "TEACHER", "FACULTY", "DEPARTMENT")


def project_root() -> Path:
    env_root = os.getenv("LABBOT_ROOT")
    if env_root:
        return Path(env_root).expanduser().resolve()
    if getattr(sys, "frozen", False):
        return Path.home() / "Documents" / "LabBot"
    return Path(__file__).resolve().parents[2]


def settings_path(root: Optional[Path] = None) -> Path:
    return Path(root) / "settings.json" if root else project_root() / "settings.json"


def env_path(root: Optional[Path] = None) -> Path:
    return Path(root) / ".env" if root else project_root() / ".env"


def default_settings() -> Dict[str, Any]:
    return {
        "llm": dict(DEFAULT_LLM),
        "report": dict(DEFAULT_REPORT),
        "prompts": dict(DEFAULT_PROMPTS),
    }


def _as_float(value: Any, fallback: float, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return fallback
    return max(minimum, min(maximum, number))


def _as_int(value: Any, fallback: int, minimum: int, maximum: int) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return fallback
    return max(minimum, min(maximum, number))


def normalize_settings(raw: Mapping[str, Any]) -> Dict[str, Any]:
    data = default_settings()
    llm = raw.get("llm") if isinstance(raw.get("llm"), Mapping) else {}
    report = raw.get("report") if isinstance(raw.get("report"), Mapping) else {}

    model = str(llm.get("model") or DEFAULT_LLM["model"]).strip() or DEFAULT_LLM["model"]
    base_url = str(llm.get("base_url") or DEFAULT_LLM["base_url"]).strip() or DEFAULT_LLM["base_url"]
    if not base_url.startswith(("http://", "https://")):
        base_url = DEFAULT_LLM["base_url"]

    provider = str(llm.get("provider") or "deepseek").strip().lower()
    if provider not in PROVIDERS:
        provider = "deepseek"

    data["llm"] = {
        "provider": provider,
        "model": model,
        "base_url": base_url,
        "temperature": _as_float(llm.get("temperature", DEFAULT_LLM["temperature"]), 0.2, 0.0, 2.0),
        "max_tokens": _as_int(llm.get("max_tokens", DEFAULT_LLM["max_tokens"]), 8192, 512, 65536),
        "timeout": _as_int(llm.get("timeout", DEFAULT_LLM["timeout"]), 180, 10, 900),
        "max_retries": _as_int(llm.get("max_retries", DEFAULT_LLM["max_retries"]), 4, 0, 10),
        "max_cost_limit_usd": _as_float(
            llm.get("max_cost_limit_usd", DEFAULT_LLM["max_cost_limit_usd"]), 1.0, 0.01, 100.0
        ),
    }
    data["report"] = {"year": re.sub(r"\D", "", str(report.get("year") or ""))[:4]}
    data["prompts"] = merge_prompts(raw.get("prompts") if isinstance(raw.get("prompts"), Mapping) else None)
    return data


def load_settings(root: Optional[Path] = None) -> Dict[str, Any]:
    path = settings_path(root)
    if not path.exists():
        return default_settings()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default_settings()
    if not isinstance(raw, Mapping):
        return default_settings()
    return normalize_settings(raw)


def save_settings(data: Mapping[str, Any], root: Optional[Path] = None) -> Path:
    path = settings_path(root)
    normalized = normalize_settings(data)
    path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


# --- .env -------------------------------------------------------------------

def parse_env(text: str) -> Dict[str, str]:
    values: Dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def read_env(root: Optional[Path] = None) -> Dict[str, str]:
    path = env_path(root)
    if not path.exists():
        return {}
    return parse_env(path.read_text(encoding="utf-8", errors="ignore"))


def write_env_values(values: Mapping[str, str], root: Optional[Path] = None) -> Path:
    path = env_path(root)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    for key, value in values.items():
        if not key:
            continue
        pattern = re.compile(rf"^\s*{re.escape(key)}\s*=")
        for idx, line in enumerate(lines):
            if pattern.match(line):
                lines[idx] = f"{key}={value}"
                break
        else:
            lines.append(f"{key}={value}")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return path


def api_key(root: Optional[Path] = None) -> str:
    return read_env(root).get("DEEPSEEK_API_KEY", "") or os.getenv("DEEPSEEK_API_KEY", "")


def mask_key(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if len(value) <= 10:
        return "••••"
    return f"{value[:5]}…{value[-4:]}"


def profile_from_env(root: Optional[Path] = None) -> Dict[str, str]:
    env = read_env(root)
    return {
        "student": env.get("STUDENT", ""),
        "group": env.get("GROUP", ""),
        "teacher": env.get("TEACHER", ""),
        "faculty": env.get("FACULTY", ""),
        "department": env.get("DEPARTMENT", ""),
    }
