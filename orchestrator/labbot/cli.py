import argparse
import logging
import os
import sys
from pathlib import Path
from .compile import compile_all, compile_docx, compile_latex
from .generate import PipelineRunner
from .llm import DeepSeekClient
from .profile import Profile, describe, prompt_profile, save_to_env
from .settings import api_key as settings_api_key, load_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("mtuci-labbot.cli")


def main():
    parser = argparse.ArgumentParser(description="mtuci-labbot CLI")
    subparsers = parser.add_subparsers(dest="command")

    p_report = subparsers.add_parser("report", help="Сгенерировать отчёт")
    p_report.add_argument("lab_dir", type=Path)
    p_report.add_argument("--variant", type=str, default=None, help="Номер варианта")
    p_report.add_argument("--pages", type=str, default=None)
    p_report.add_argument("--fast", action="store_true")
    p_report.add_argument("--from-stage", type=str, default=None)
    p_report.add_argument("--student", type=str, default=None, help="ФИО того, кто выполнил")
    p_report.add_argument("--group", type=str, default=None, help="Группа")
    p_report.add_argument("--teacher", type=str, default=None, help="ФИО преподавателя")
    p_report.add_argument("--faculty", type=str, default=None)
    p_report.add_argument("--department", type=str, default=None)
    p_report.add_argument(
        "--remember",
        action="store_true",
        help="Сохранить введённые ФИО в .env для следующих запусков",
    )

    p_docx = subparsers.add_parser("docx", help="Собрать только Word")
    p_docx.add_argument("lab_dir", type=Path)

    p_tex = subparsers.add_parser("tex", help="Собрать только PDF")
    p_tex.add_argument("lab_dir", type=Path)

    p_build = subparsers.add_parser("build", help="Оффлайн сборка")
    p_build.add_argument("lab_dir", type=Path)

    subparsers.add_parser("sanity", help="Проверка окружения")

    args = parser.parse_args()

    if args.command == "sanity":
        sys.exit(0)

    if args.command == "report":
        variant = args.variant
        if not variant:
            print("\n" + "=" * 50)
            try:
                variant = input(">>> Введите ваш вариант (например, 1): ").strip()
            except (KeyboardInterrupt, EOFError):
                variant = "1"
            print("=" * 50 + "\n")

        profile = Profile.from_env().with_overrides(
            student=args.student,
            group=args.group,
            teacher=args.teacher,
            faculty=args.faculty,
            department=args.department,
        )

        if sys.stdin.isatty():
            profile = prompt_profile(profile)
        elif not profile.student:
            logger.warning(
                "ФИО исполнителя не задано: титульный лист будет без строки «Выполнил». "
                "Передайте --student \"Фамилия И.О.\""
            )

        if args.remember:
            env_path = save_to_env(Path(os.getenv("LABBOT_ENV_FILE", ".env")), profile)
            print(f"Данные титульного листа сохранены в {env_path}")

        print(describe(profile))

        settings = load_settings()
        llm = settings["llm"]
        if settings.get("report", {}).get("year"):
            os.environ["REPORT_YEAR"] = str(settings["report"]["year"])

        client = DeepSeekClient(
            api_key=settings_api_key() or None,
            base_url=llm["base_url"],
            model=llm["model"],
            timeout=float(llm["timeout"]),
            max_retries=int(llm["max_retries"]),
            max_cost_limit=float(llm["max_cost_limit_usd"]),
            temperature=float(llm["temperature"]),
            max_tokens=int(llm["max_tokens"]),
        )
        runner = PipelineRunner(
            lab_dir=args.lab_dir,
            client=client,
            variant=variant if variant else "1",
            fast_mode=args.fast,
            from_stage=args.from_stage,
            pages=args.pages,
            profile=profile,
            prompts=settings["prompts"],
            settings=settings,
        )
        runner.run()
        sys.exit(0)

    if args.command == "docx":
        lab_dir = args.lab_dir.resolve()
        ok = compile_docx(lab_dir / "build", lab_dir)
        sys.exit(0 if ok else 1)

    if args.command == "tex":
        lab_dir = args.lab_dir.resolve()
        ok = compile_latex(lab_dir / "build")
        sys.exit(0 if ok else 1)

    if args.command == "build":
        lab_dir = args.lab_dir.resolve()
        res = compile_all(lab_dir / "build", lab_dir)
        sys.exit(0 if (res.get("pdf") or res.get("docx")) else 1)

    parser.print_help()


if __name__ == "__main__":
    main()
