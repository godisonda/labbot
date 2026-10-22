"""Точка входа для упакованного приложения (PyInstaller).

Обычный запуск — графическая оболочка. С флагом --run-cli — тот же процесс
выполняет команду пайплайна (так GUI запускает генерацию без внешнего Python).

Импорты намеренно ленивые: CLI тянет matplotlib/openai, и без этого оболочка
стартовала бы на несколько секунд дольше.
"""
from __future__ import annotations

import sys


def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] == "--run-cli":
        from orchestrator.labbot import cli as labbot_cli

        sys.argv = [sys.argv[0], *sys.argv[2:]]
        labbot_cli.main()
        return 0

    from orchestrator.labbot.gui import main as gui_main

    return gui_main()


if __name__ == "__main__":
    raise SystemExit(main())
