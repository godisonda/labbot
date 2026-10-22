import json

import pytest

from orchestrator.labbot.prompts import DEFAULT_PROMPTS, merge_prompts, render_prompt
from orchestrator.labbot.settings import (
    api_key,
    default_settings,
    load_settings,
    mask_key,
    read_env,
    save_settings,
    write_env_values,
)


def test_defaults_shape():
    data = default_settings()
    assert set(data["llm"]) >= {"model", "base_url", "temperature", "max_retries"}
    assert set(data["prompts"]) == set(DEFAULT_PROMPTS)
    assert data["prompts"]["section"] == DEFAULT_PROMPTS["section"]


def test_save_and_load_roundtrip(tmp_path):
    path = save_settings(
        {
            "llm": {"model": "deepseek-reasoner", "temperature": 0.7, "max_cost_limit_usd": 3.5},
            "report": {"year": "2027"},
            "prompts": {"system": "Мой промпт"},
        },
        tmp_path,
    )
    assert path == tmp_path / "settings.json"

    loaded = load_settings(tmp_path)
    assert loaded["llm"]["model"] == "deepseek-reasoner"
    assert loaded["llm"]["temperature"] == 0.7
    assert loaded["llm"]["max_cost_limit_usd"] == 3.5
    assert loaded["report"]["year"] == "2027"
    assert loaded["prompts"]["system"] == "Мой промпт"
    # остальные промпты — стандартные
    assert loaded["prompts"]["outline"] == DEFAULT_PROMPTS["outline"]


def test_normalization_clamps_values(tmp_path):
    save_settings(
        {
            "llm": {"temperature": 99, "max_retries": -5, "max_tokens": 999999, "base_url": "ftp://x"},
            "report": {"year": "20x7 год"},
        },
        tmp_path,
    )
    loaded = load_settings(tmp_path)
    assert loaded["llm"]["temperature"] == 2.0
    assert loaded["llm"]["max_retries"] == 0
    assert loaded["llm"]["max_tokens"] == 65536
    assert loaded["llm"]["base_url"] == "https://api.deepseek.com"
    assert loaded["report"]["year"] == "207"


def test_broken_settings_file_falls_back(tmp_path):
    (tmp_path / "settings.json").write_text("{не json", encoding="utf-8")
    assert load_settings(tmp_path)["llm"]["model"] == "deepseek-chat"


def test_prompt_render_and_merge():
    text = render_prompt("Привет <<name>>, вариант <<variant>>", {"name": "Иван"})
    assert text == "Привет Иван, вариант <<variant>>"

    merged = merge_prompts({"system": "  ", "outline": "Мой анализ"})
    assert merged["system"] == DEFAULT_PROMPTS["system"]
    assert merged["outline"] == "Мой анализ"


def test_env_roundtrip_and_key(tmp_path):
    write_env_values({"DEEPSEEK_API_KEY": "test-key-abcdef1234567890", "STUDENT": "Иванов И.И."}, tmp_path)
    write_env_values({"STUDENT": "Смирнов С.С."}, tmp_path)

    env = read_env(tmp_path)
    assert env["STUDENT"] == "Смирнов С.С."
    assert api_key(tmp_path) == "test-key-abcdef1234567890"
    assert env["DEEPSEEK_API_KEY"] == "test-key-abcdef1234567890"


def test_mask_key():
    assert mask_key("") == ""
    assert mask_key("short") == "••••"
    assert mask_key("abcdefghijklmnop").startswith("abcde")
    assert mask_key("abcdefghijklmnop").endswith("mnop")


def test_settings_file_is_valid_json(tmp_path):
    save_settings({"llm": {"model": "deepseek-chat"}}, tmp_path)
    raw = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert raw["llm"]["model"] == "deepseek-chat"


def test_custom_prompt_reaches_model(tmp_path):
    from unittest.mock import MagicMock

    from orchestrator.labbot.generate import PipelineRunner
    from orchestrator.labbot.schemas import LabOutline, MetaInfo

    outline = LabOutline(meta=MetaInfo(title="Тест"), sections=[])
    client = MagicMock()
    client.generate_structured.return_value = outline

    prompts = dict(DEFAULT_PROMPTS)
    prompts["system"] = "СИСТЕМА-X"
    prompts["outline"] = "ШАБЛОН-X вариант <<variant>>: <<methodichka>>"

    (tmp_path / "build").mkdir()
    runner = PipelineRunner(lab_dir=tmp_path, client=client, prompts=prompts, variant="5")

    runner._step_outline("ТЕКСТ МЕТОДИЧКИ")

    messages = client.generate_structured.call_args.args[0]
    assert messages[0]["content"] == "СИСТЕМА-X"
    assert messages[1]["content"] == "ШАБЛОН-X вариант 5: ТЕКСТ МЕТОДИЧКИ"


def test_provider_default_and_normalization(tmp_path):
    assert load_settings(tmp_path)["llm"]["provider"] == "deepseek"

    save_settings({"llm": {"provider": "openrouter", "model": "openai/gpt-4o-mini"}}, tmp_path)
    assert load_settings(tmp_path)["llm"]["provider"] == "openrouter"

    save_settings({"llm": {"provider": "unknown-provider"}}, tmp_path)
    assert load_settings(tmp_path)["llm"]["provider"] == "deepseek"
