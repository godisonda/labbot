"""Профиль исполнителя отчёта: ФИО студента, группа, преподаватель.

В коде нет зашитых ФИО: значения берутся из аргументов CLI, затем из .env,
а недостающие — спрашиваются в консоли (см. prompt_profile).
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Dict, Optional

ENV_KEYS = {
    "student": "STUDENT",
    "group": "GROUP",
    "teacher": "TEACHER",
    "faculty": "FACULTY",
    "department": "DEPARTMENT",
}


@dataclass(frozen=True)
class Profile:
    student: str = ""
    group: str = ""
    teacher: str = ""
    faculty: str = ""
    department: str = ""

    @classmethod
    def from_env(cls) -> "Profile":
        return cls(**{f: (os.getenv(ENV_KEYS[f], "") or "").strip() for f in ENV_KEYS})

    def with_overrides(self, **values: Optional[str]) -> "Profile":
        """Возвращает копию профиля, заменяя только переданные непустые поля."""
        clean = {
            key: value.strip()
            for key, value in values.items()
            if key in ENV_KEYS and isinstance(value, str) and value.strip()
        }
        return replace(self, **clean) if clean else self

    def as_dict(self) -> Dict[str, str]:
        return {name: getattr(self, name) for name in ENV_KEYS}


def _ask(label: str, default: str = "", required: bool = False) -> str:
    hint = f" [{default}]" if default else ""
    while True:
        try:
            raw = input(f">>> {label}{hint}: ").strip()
        except (KeyboardInterrupt, EOFError):
            print()
            raw = ""
        value = raw or default
        if value or not required:
            return value
        print("    Поле обязательное — введите ещё раз (Ctrl+C — отмена).")


def prompt_profile(profile: Profile) -> Profile:
    """Спрашивает ФИО в консоли. Enter — оставить текущее значение."""
    print("\n" + "=" * 58)
    print(" Титульный лист: кто выполнил и кто проверил")
    print("=" * 58)
    student = _ask("ФИО студента (кто выполнил работу)", profile.student, required=True)
    group = _ask("Группа", profile.group)
    teacher = _ask("ФИО преподавателя (Enter — не указывать)", profile.teacher)
    print("=" * 58 + "\n")
    return replace(profile, student=student, group=group, teacher=teacher)


def save_to_env(env_path: Path, profile: Profile) -> Path:
    """Обновляет ключи профиля в .env, не трогая остальные строки."""
    env_path = Path(env_path)
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []

    for name, key in ENV_KEYS.items():
        value = getattr(profile, name).strip()
        if not value:
            continue
        if "#" in value:
            value = f'"{value}"'
        pattern = re.compile(rf"^\s*{re.escape(key)}\s*=")
        for idx, line in enumerate(lines):
            if pattern.match(line):
                lines[idx] = f"{key}={value}"
                break
        else:
            lines.append(f"{key}={value}")

    env_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return env_path


def describe(profile: Profile) -> str:
    student = profile.student or "не указан"
    group = f", гр. {profile.group}" if profile.group else ""
    teacher = profile.teacher or "не указан"
    return f"Выполнил: {student}{group} | Преподаватель: {teacher}"
