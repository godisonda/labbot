#!/bin/zsh
# Двойной клик в Finder — запуск графической оболочки LabBot.
cd "$(dirname "$0")" || exit 1
exec make gui
