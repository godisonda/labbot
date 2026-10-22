import json
from typing import List

import openai
import pytest
from pydantic import BaseModel
from unittest.mock import MagicMock, patch

from orchestrator.labbot.generate import GenerationState, PipelineRunner
from orchestrator.labbot.llm import DeepSeekAPIError, DeepSeekClient
from orchestrator.labbot.profile import Profile
from orchestrator.labbot.prompts import DEFAULT_PROMPTS


class Question(BaseModel):
    question: str
    answer: str


class CheckQuestions(BaseModel):
    items: List[Question]


def _response(content: str, prompt_tokens: int = 10, completion_tokens: int = 10) -> MagicMock:
    resp = MagicMock()
    resp.choices = [MagicMock(message=MagicMock(content=content))]
    resp.usage = MagicMock(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        prompt_tokens_details=None,
    )
    return resp


def test_missing_api_key_raises_error(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(DeepSeekAPIError) as exc_info:
        DeepSeekClient(api_key=None)
    assert "DEEPSEEK_API_KEY не задан" in str(exc_info.value)


def test_text_generation_success():
    client = DeepSeekClient(api_key="test-mock-key")
    resp = _response("Тестовый раздел отчета", 100, 50)

    with patch.object(client.client.chat.completions, "create", return_value=resp):
        res = client.generate_text([{"role": "user", "content": "hello"}])
        assert res == "Тестовый раздел отчета"
        assert client.total_prompt_tokens == 100
        assert client.total_completion_tokens == 50


def test_structured_json_success():
    client = DeepSeekClient(api_key="test-mock-key")
    payload = {
        "items": [
            {"question": "Что такое АЧХ?", "answer": "Амплитудно-частотная характеристика."},
            {"question": "Что такое ФЧХ?", "answer": "Фазо-частотная характеристика."},
        ]
    }

    with patch.object(client.client.chat.completions, "create", return_value=_response(json.dumps(payload))):
        res = client.generate_structured([{"role": "user", "content": "generate qa"}], CheckQuestions)
        assert isinstance(res, CheckQuestions)
        assert len(res.items) == 2
        assert res.items[0].question == "Что такое АЧХ?"


def test_error_handling_401():
    client = DeepSeekClient(api_key="test-mock-key")
    mock_err = openai.AuthenticationError(
        message="Invalid API Key",
        response=MagicMock(status_code=401),
        body=None,
    )

    with patch.object(client.client.chat.completions, "create", side_effect=mock_err):
        with pytest.raises(DeepSeekAPIError) as exc_info:
            client.generate_text([{"role": "user", "content": "test"}])
        assert "401" in str(exc_info.value)


def test_error_handling_insufficient_balance():
    client = DeepSeekClient(api_key="test-mock-key")
    mock_err = openai.APIStatusError(
        message="Insufficient Balance on account",
        response=MagicMock(status_code=402),
        body=None,
    )

    with patch.object(client.client.chat.completions, "create", side_effect=mock_err):
        with pytest.raises(DeepSeekAPIError) as exc_info:
            client.generate_text([{"role": "user", "content": "test"}])
        assert "Недостаточно средств на балансе" in str(exc_info.value)


def test_state_management_and_resume(tmp_path):
    state = GenerationState(tmp_path / "state.json")

    state.mark_step_done("extract")
    state.mark_step_done("outline")
    state.mark_step_done("section_intro")

    assert state.is_step_done("extract") is True
    assert state.is_step_done("outline") is True
    assert state.is_step_done("section_intro") is True

    state.reset_from("outline")
    assert state.is_step_done("extract") is True
    assert state.is_step_done("outline") is False
    assert state.is_step_done("section_intro") is False


def test_smoke_mock_pipeline(tmp_path):
    """Полный пайплайн на моках: задание → outline → скрипт → разделы → сборка."""
    lab_dir = tmp_path / "lab_test"
    lab_dir.mkdir()
    (lab_dir / "ТЗ.txt").write_text(
        "Лабораторная работа №1 по ТЭС. Исследование фильтров.", encoding="utf-8"
    )
    (lab_dir / "refs").mkdir()
    (lab_dir / "refs" / "образец.txt").write_text("Пример оформления отчёта.", encoding="utf-8")

    outline_payload = {
        "meta": {
            "number": "1",
            "title": "Исследование фильтров",
            "discipline": "ТЭС",
            "department": "Кафедра ТЭС",
            "goal": "Изучение АЧХ",
            "has_source_code": False,
            "code_language": "cpp",
        },
        "flowcharts": [],
        "visuals": [],
        "sections": [
            {"id": "task", "title": "1 Постановка задачи", "guidance": "Цель и задачи"},
            {"id": "conclusion", "title": "2 Выводы", "guidance": "Итоги"},
        ],
    }

    client = DeepSeekClient(api_key="test-mock-key")
    responses = [
        _response(json.dumps(outline_payload)),
        _response("print('ok')"),
        _response("Текст раздела про фильтры."),
        _response("Текст выводов."),
    ]

    profile = Profile(student="Иванов И.И.", group="ГР-1", teacher="Смирнов С.С.")

    with patch.object(client.client.chat.completions, "create", side_effect=responses) as mocked_create:
        with patch("orchestrator.labbot.generate.compile_all", return_value={"pdf": True, "docx": False}):
            runner = PipelineRunner(
                lab_dir=lab_dir, client=client, variant="2", fast_mode=True,
                profile=profile, prompts=dict(DEFAULT_PROMPTS),
            )
            runner.run()

    assert (lab_dir / "build" / "state.json").exists()
    combined = (lab_dir / "build" / "report_combined.md").read_text(encoding="utf-8")
    assert "Текст раздела про фильтры." in combined

    tex = (lab_dir / "build" / "main.tex").read_text(encoding="utf-8")
    assert "Иванов И.И." in tex
    assert "Смирнов С.С." in tex

    assert runner.reference_text.startswith("--- образец.txt ---")

    # образец должен попасть в промпт анализа структуры и в промпты разделов
    prompts = [call.kwargs["messages"][1]["content"] for call in mocked_create.call_args_list]
    assert any("ОБРАЗЕЦ ГОТОВОЙ РАБОТЫ" in prompt for prompt in prompts)
    assert any("Пример оформления отчёта." in prompt for prompt in prompts)
