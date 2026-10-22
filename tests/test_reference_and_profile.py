from pathlib import Path
from unittest.mock import MagicMock

import pytest

from orchestrator.labbot.assemble import assemble_report_tex
from orchestrator.labbot.extract import find_lab_documents
from orchestrator.labbot.profile import Profile, prompt_profile, save_to_env
from orchestrator.labbot.schemas import LabOutline, MetaInfo, SectionSpec


# --- поиск задания и образца ------------------------------------------------

def test_task_and_example_by_name(tmp_path):
    (tmp_path / "ТЗ.txt").write_text("задание", encoding="utf-8")
    (tmp_path / "образец.txt").write_text("пример", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("вариант 3", encoding="utf-8")

    main, refs = find_lab_documents(tmp_path)

    assert main is not None and main.name == "ТЗ.txt"
    assert [p.name for p in refs] == ["образец.txt"]


def test_example_from_refs_subfolder(tmp_path):
    (tmp_path / "Задание.txt").write_text("задание", encoding="utf-8")
    refs_dir = tmp_path / "refs"
    refs_dir.mkdir()
    (refs_dir / "Прошлогодний отчёт.txt").write_text("пример", encoding="utf-8")

    main, refs = find_lab_documents(tmp_path)

    assert main.name == "Задание.txt"
    assert [p.name for p in refs] == ["Прошлогодний отчёт.txt"]


def test_tz_has_priority_over_methodichka(tmp_path):
    (tmp_path / "Методичка.txt").write_text("методичка", encoding="utf-8")
    (tmp_path / "ТЗ.txt").write_text("тз", encoding="utf-8")

    main, _ = find_lab_documents(tmp_path)
    assert main.name == "ТЗ.txt"


def test_only_example_used_as_task(tmp_path):
    (tmp_path / "образец.txt").write_text("единственный файл", encoding="utf-8")

    main, refs = find_lab_documents(tmp_path)
    assert main is not None and main.name == "образец.txt"
    assert refs == []


def test_no_documents(tmp_path):
    (tmp_path / "main.cpp").write_text("int main(){}", encoding="utf-8")
    assert find_lab_documents(tmp_path) == (None, [])


# --- профиль ----------------------------------------------------------------

def test_profile_from_env_and_overrides(monkeypatch):
    monkeypatch.setenv("STUDENT", "Старое И.И.")
    monkeypatch.setenv("TEACHER", "")
    monkeypatch.setenv("GROUP", "ГР-1")

    profile = Profile.from_env().with_overrides(student="Новое Н.Н.", teacher="Препод П.П.")

    assert profile.student == "Новое Н.Н."
    assert profile.teacher == "Препод П.П."
    assert profile.group == "ГР-1"


def test_prompt_profile(monkeypatch):
    answers = iter(["Иванов И.И.", "", "Сидоров С.С."])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(answers))

    result = prompt_profile(Profile(group="ГР-2"))

    assert result.student == "Иванов И.И."
    assert result.group == "ГР-2"
    assert result.teacher == "Сидоров С.С."


def test_save_to_env_updates_and_appends(tmp_path):
    env = tmp_path / ".env"
    env.write_text("DEEPSEEK_MODEL=deepseek-chat\nSTUDENT=Старое И.И.\n", encoding="utf-8")

    save_to_env(env, Profile(student="Новое Н.Н.", teacher="Препод П.П."))
    content = env.read_text(encoding="utf-8")

    assert "DEEPSEEK_MODEL=deepseek-chat" in content
    assert "STUDENT=Новое Н.Н." in content
    assert "TEACHER=Препод П.П." in content
    assert "Старое И.И." not in content


# --- титульный лист ---------------------------------------------------------

def _outline(**meta_overrides) -> LabOutline:
    meta_data = {
        "number": "1",
        "title": "Тестовая работа",
        "discipline": "ТЭС",
        "department": "Кафедра ТЭС",
    }
    meta_data.update(meta_overrides)
    return LabOutline(
        meta=MetaInfo(**meta_data),
        sections=[SectionSpec(id="task", title="1 Постановка задачи", guidance="Цель")],
    )


def test_title_page_uses_profile(tmp_path):
    profile = Profile(
        student="Иванов И.И.", group="ГР-1", teacher="Смирнов С.С.", faculty="ИТ"
    )
    assemble_report_tex(tmp_path, _outline(), {"task": "Текст раздела."}, profile=profile)

    tex = (tmp_path / "build" / "main.tex").read_text(encoding="utf-8")
    word = (tmp_path / "build" / "report_for_word.md").read_text(encoding="utf-8")

    assert "Иванов И.И." in tex and "Иванов И.И." in word
    assert "Смирнов С.С." in tex and "Смирнов С.С." in word
    assert "ст. гр. ГР-1" in tex
    assert "Смирнов С.С." in tex


def test_title_page_without_teacher(tmp_path):
    profile = Profile(student="Иванов И.И.", group="ГР-1")
    assemble_report_tex(tmp_path, _outline(), {"task": "Текст."}, profile=profile)

    tex = (tmp_path / "build" / "main.tex").read_text(encoding="utf-8")
    assert "Проверил" not in tex
    assert "Выполнил" in tex


def test_title_page_without_names(tmp_path):
    assemble_report_tex(tmp_path, _outline(), {"task": "Текст."}, profile=Profile())

    tex = (tmp_path / "build" / "main.tex").read_text(encoding="utf-8")
    assert "Выполнил" not in tex
    assert "Проверил" not in tex


# --- тип работы -------------------------------------------------------------

def test_work_type_default_is_lab(tmp_path):
    assemble_report_tex(tmp_path, _outline(), {"task": "Текст."}, profile=Profile())

    tex = (tmp_path / "build" / "main.tex").read_text(encoding="utf-8")
    assert "ОТЧЕТ ПО ЛАБОРАТОРНОЙ РАБОТЕ №1" in tex
    assert "Лабораторная работа №1" in tex


def test_work_type_explicit_for_credit(tmp_path):
    outline = _outline(work_type="Зачётная работа", work_type_po="ЗАЧЁТНОЙ РАБОТЕ")
    assemble_report_tex(tmp_path, outline, {"task": "Текст."}, profile=Profile())

    tex = (tmp_path / "build" / "main.tex").read_text(encoding="utf-8")
    word = (tmp_path / "build" / "report_for_word.md").read_text(encoding="utf-8")

    assert "ОТЧЕТ ПО ЗАЧЁТНОЙ РАБОТЕ №1" in tex
    assert "Зачётная работа №1" in tex
    assert "ОТЧЕТ ПО ЗАЧЁТНОЙ РАБОТЕ №1" in word
    assert "Зачётная работа №1." in word


def test_work_type_credit_noun(tmp_path):
    outline = _outline(work_type="Зачёт", work_type_po="ЗАЧЁТУ")
    assemble_report_tex(tmp_path, outline, {"task": "Текст."}, profile=Profile())

    tex = (tmp_path / "build" / "main.tex").read_text(encoding="utf-8")
    assert "ОТЧЕТ ПО ЗАЧЁТУ №1" in tex
    assert "Зачёт №1" in tex


def test_work_type_derived_when_po_missing(tmp_path):
    outline = _outline(work_type="Практическая работа")
    assemble_report_tex(tmp_path, outline, {"task": "Текст."}, profile=Profile())

    tex = (tmp_path / "build" / "main.tex").read_text(encoding="utf-8")
    assert "ОТЧЕТ ПО ПРАКТИЧЕСКОЙ РАБОТЕ №1" in tex
    assert "Практическая работа №1" in tex


def test_work_type_uppercase_normalized(tmp_path):
    outline = _outline(work_type="ЛАБОРАТОРНАЯ РАБОТА")
    assemble_report_tex(tmp_path, outline, {"task": "Текст."}, profile=Profile())

    tex = (tmp_path / "build" / "main.tex").read_text(encoding="utf-8")
    assert "Лабораторная работа №1" in tex


def test_old_outline_without_work_type_still_loads():
    old_meta = MetaInfo.model_validate({"number": "4", "title": "Старый кэш"})
    assert old_meta.work_type == "Лабораторная работа"
    assert old_meta.work_type_po == ""


def test_broken_reference_is_skipped(tmp_path):
    from orchestrator.labbot.generate import PipelineRunner

    bad = tmp_path / "refs" / "broken.docx"
    bad.parent.mkdir()
    bad.write_bytes(b"not a docx")

    runner = PipelineRunner(lab_dir=tmp_path, client=MagicMock())
    text = runner._prepare_references([bad], tmp_path / "build" / "refs_raw.txt")

    assert text == ""
