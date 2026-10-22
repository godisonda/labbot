# LabBot

[![tests](https://github.com/godisonda/labbot/actions/workflows/tests.yml/badge.svg)](https://github.com/godisonda/labbot/actions/workflows/tests.yml) [![release](https://img.shields.io/github/v/release/godisonda/labbot)](https://github.com/godisonda/labbot/releases)

Локальное приложение для подготовки отчётов по лабораторным и практическим работам:
на вход — методичка или ТЗ, на выходе — готовый PDF по шаблону кафедры и версия для Word.

Внутри — конвейер из пяти шагов: разбор документа → структура отчёта → код и его проверка →
графики и таблицы → текст разделов → сборка `main.pdf` и `report.docx`. Тексты пишет
DeepSeek API, а числа берутся из реально запущенной программы и скриптов, чтобы листинг,
таблицы и выводы совпадали между собой.

> Инструмент автоматизирует оформление и черновик. Проверяйте факты, формулы и выводы
> перед сдачей: ответственность за работу остаётся на вас.

## Содержание

- [Что умеет](#что-умеет)
- [Как это работает](#как-это-работает)
- [Требования](#требования)
- [Установка](#установка)
- [API-ключ DeepSeek](#api-ключ-deepseek)
- [Быстрый старт](#быстрый-старт)
- [Графическая оболочка](#графическая-оболочка)
- [Настройки](#настройки)
- [Папка работы](#папка-работы)
- [Команды Makefile и CLI](#команды-makefile-и-cli)
- [Что получается на выходе](#что-получается-на-выходе)
- [Сборка приложения](#сборка-приложения)
- [Docker](#docker)
- [Тесты](#тесты)
- [Структура репозитория](#структура-репозитория)
- [Безопасность и приватность](#безопасность-и-приватность)
- [Устранение неполадок](#устранение-неполадок)
- [Лицензия](#лицензия)

## Что умеет

- **Входные форматы:** PDF, DOCX, TXT, MD. Таблицы из DOCX извлекаются в Markdown, из PDF — текст.
- **Работа по образцу:** рядом с заданием можно положить готовый отчёт или ТЗ — модель повторит
  его структуру, стиль и оформление, но данные возьмёт из вашего варианта.
- **Свой код:** если работа программируемая, модель пишет исходник, скрипт компилируется (`g++`)
  и запускается; реальный вывод программы становится единой базой фактов для всех разделов.
- **Графики и блок-схемы:** скрипт на matplotlib строит рисунки, блок-схема рисуется по ГОСТ 19.701-90.
- **Титульный лист:** ФИО студента и преподавателя, группа, кафедра, дисциплина, год. Тип работы
  (лабораторная, практическая, зачётная, курсовая, зачёт) определяется по документу.
- **Графическая оболочка:** простой светлый интерфейс с плавными анимациями, список работ,
  drag & drop документов, ввод ФИО, настройки API и промптов, живой журнал, прогресс и результаты.
- **Экономия и защита бюджета:** кэш шагов (`state.json`), дозапуск с любого этапа, лимит расходов.
- **Экспорт:** PDF (XeLaTeX) и DOCX (Pandoc + стили ГОСТ), исходники, скрипты, рисунки.
- **Не только DeepSeek:** подойдёт любой OpenAI-совместимый API — OpenAI, OpenRouter, Ollama, LM Studio.

## Как это работает

```
методичка/ТЗ ─┐
              ├─► extract ─► outline ─► code ─► scripts ─► sections ─► assemble ─► main.pdf
образец (refs)┘      │           │          │         │          │            │
                     ▼           ▼          ▼         ▼          ▼            ▼
               текст+таблицы  структура  main.cpp  fig*.png  разделы .md  main.tex + .docx
                              и тип       + stdout  + flowchart
```

1. **extract** — читает документы, отделяет задание от образца, подмешивает `notes.txt` и номер варианта.
2. **outline** — модель возвращает строгий JSON (pydantic-схема): тема, кафедра, тип работы, полная
   спецификация варианта, список разделов, рисунков и цепочек блок-схем.
3. **code** — генерация `main.cpp`/`main.py`, компиляция и тестовый запуск; ошибки компилятора
   отправляются модели на исправление (до 3 попыток). Реальный `stdout` сохраняется.
4. **scripts** — matplotlib-скрипт графиков (запускается локально) и отрисовка блок-схемы.
5. **sections** — разделы пишутся по одному, с памятью о предыдущих; раздел «Листинг» заполняется
   кодом напрямую, без участия модели.
6. **assemble** — титульный лист, `main.tex`, сборка PDF через `latexmk`/`xelatex`, DOCX через Pandoc.

Каждый успешный шаг отмечается в `build/state.json`, поэтому прерванный запуск продолжается
с места сбоя, а не с нуля.

## Требования

| Компонент | Зачем | Обязателен |
|---|---|---|
| Python 3.10+ | сам LabBot | да |
| DeepSeek API-ключ | генерация текста | да |
| TeX Live (`xelatex`, `latexmk`) | сборка PDF | да для PDF |
| Pandoc | сборка DOCX | да для Word |
| `g++` | работы на C++ | только для C++ |
| Docker | запуск без установки TeX | опционально |

## Установка

### macOS

```bash
brew install python@3.12 pandoc
brew install --cask mactex-no-gui   # или полный MacTeX; нужны xelatex и latexmk
xcode-select --install              # g++

git clone https://github.com/godisonda/labbot.git
cd mtuci-labbot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Makefile сам подхватывает `.venv/bin/python`, если папка существует, — активировать venv не обязательно.

### Linux (Debian/Ubuntu)

```bash
sudo apt update
sudo apt install python3 python3-venv python3-pip pandoc \
    texlive-xetex texlive-lang-cyrillic texlive-latex-extra texlive-science latexmk \
    fonts-liberation g++

git clone https://github.com/godisonda/labbot.git
cd mtuci-labbot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### Windows

1. Python 3.10+ с [python.org](https://www.python.org/downloads/) (галочка «Add Python to PATH»).
2. [Pandoc](https://pandoc.org/installing.html).
3. TeX: [MiKTeX](https://miktex.org/download) или TeX Live; проверьте `xelatex --version`.
4. Для C++ — MSYS2 с `g++` или Visual Studio Build Tools.
5. В PowerShell:

```powershell
git clone https://github.com/godisonda/labbot.git
cd mtuci-labbot
python -m pip install -r requirements.txt
copy .env.example .env
```

Команды `make` на Windows нет — используйте Python напрямую:

```powershell
python -m orchestrator.labbot.gui
python -m orchestrator.labbot.cli report labs/lab_01 --variant 1
```

### Docker

См. раздел [Docker](#docker). В образе уже есть TeX Live, Pandoc, poppler и шрифты.

## API-ключ DeepSeek

1. Зарегистрируйтесь на [platform.deepseek.com](https://platform.deepseek.com).
2. Пополните баланс и создайте ключ в разделе **API keys**.
3. Вставьте его одним из способов:
   - в файл `.env`: `DEEPSEEK_API_KEY=sk-...`;
   - в графической оболочке: **Настройки → DeepSeek API → API-ключ → Проверить ключ → Сохранить**.

Ключ хранится только в `.env` (файл в `.gitignore`) и уходит только на `api.deepseek.com`.
Стоимость одного полного отчёта — обычно несколько центов; лимит по умолчанию — **$1** за запуск,
он задаётся в настройках (`max_cost_limit_usd`). При превышении пайплайн останавливается с ошибкой.

## Быстрый старт

```bash
cp .env.example .env      # вписать DEEPSEEK_API_KEY
make gui                  # откроется http://127.0.0.1:8765
```

В оболочке:

1. **«+ Новая работа»** → номер (например `04`).
2. Перетащите в **«Задание»** методичку/ТЗ, при необходимости — образец в **«Образец / ТЗ»**.
3. Заполните ФИО, группу, преподавателя (галочка «запомнить в .env» сохранит их).
4. Укажите вариант и нажмите **▶ Запустить**.
5. Готовые `main.pdf` и `report.docx` появятся в **«Результатах»**.

Через терминал то же самое:

```bash
make new lab=04
make report lab=04 variant=1
```

## Графическая оболочка

```bash
make gui                                   # http://127.0.0.1:8765
python -m orchestrator.labbot.gui --port 9000 --no-browser
```

На macOS без терминала — двойной клик по **`LabBot GUI.command`**.

Возможности окна:

- список работ со статусами и поиском; папку можно назвать номером (`lab_05`) или своим именем;
- drag & drop задания и образца прямо в папку работы;
- ФИО и группа на главном экране, факультет и год — в «Настройках»;
- режимы запуска: полный цикл, только PDF, только Word, пересборка из `build/`;
- старт с любого этапа (`extract` … `assemble`) — например, после правки промпта;
- живой журнал, таймер, стоимость, кнопка «Остановить»;
- результаты: PDF открывается в браузере, DOCX скачивается, «Открыть папку» показывает работу в Finder/Explorer;
- «Новая работа»: название папки (номер или произвольное) и сразу задание;
- пустое состояние: большое поле «перетащите задание» по центру;
- после сборки готовые файлы появляются в том же окне, к ним плавно прокручивается страница;
- «Сбросить кэш» и «Удалить» работу (с подтверждением, вместе с файлами).

Сервер слушает только `127.0.0.1` и не требует интернета, кроме обращения к API DeepSeek.
`Ctrl/Cmd + Enter` запускает генерацию.

## Настройки

Кнопка **Настройки** в оболочке:

| Блок | Что настраивается | Куда сохраняется |
|---|---|---|
| LLM API | провайдер, ключ, модель, Base URL, температура, `max_tokens`, таймаут, повторы, лимит `$` | ключ → `.env`, остальное → `settings.json` |
| Титульный лист | ФИО, группа, факультет, кафедра, год | `.env` |
| Промпты | 7 шаблонов, кнопка «Сбросить» | `settings.json` |

`settings.json` создаётся при первом сохранении и выглядит так:

```json
{
  "llm": {
    "provider": "deepseek",
    "model": "deepseek-chat",
    "base_url": "https://api.deepseek.com",
    "temperature": 0.2,
    "max_tokens": 8192,
    "timeout": 180,
    "max_retries": 4,
    "max_cost_limit_usd": 1.0
  },
  "report": { "year": "" },
  "prompts": { "system": "…", "outline": "…", "code": "…", "scripts": "…", "section": "…" }
}
```

Если удалить `settings.json`, вернутся значения по умолчанию. Секретов в нём нет.

### Другие провайдеры

В настройках есть выбор провайдера; при смене подставляются адрес и модель, оба поля можно
поправить вручную. Ключ хранится один и уходит в `Authorization: Bearer` — поэтому подойдёт
любой сервис с OpenAI-совместимым `/chat/completions`.

| Провайдер | Base URL | Модель по умолчанию |
|---|---|---|
| DeepSeek | `https://api.deepseek.com` | `deepseek-chat` |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` |
| OpenRouter | `https://openrouter.ai/api/v1` | `openai/gpt-4o-mini` |
| Ollama / LM Studio | `http://localhost:11434/v1` | `llama3.1` |
| Другой | вводится вручную | любая |

Для локальных Ollama и LM Studio ключ не нужен, но клиент требует непустое значение —
впишите, например, `local`. Название переменной в `.env` осталось `DEEPSEEK_API_KEY`,
чтобы не ломать старые конфиги; хранится в ней ключ выбранного провайдера.

### Промпты и подстановки

Тексты промптов вынесены в `orchestrator/labbot/prompts.py` и могут быть переопределены из настроек.
Подстановки записываются как `<<имя>>` и не конфликтуют с фигурными скобками и формулами `$...$`.

| Ключ | Назначение | Подстановки |
|---|---|---|
| `system` | системная роль для всех запросов | — |
| `outline` | анализ методички и структура отчёта | `variant`, `reference`, `methodichka` |
| `code_system` | роль для генерации кода | — |
| `code` | запрос на исходный код | `language`, `title`, `variant`, `variant_summary`, `methodichka` |
| `scripts_system` | роль для скриптов графиков | — |
| `scripts` | запрос на скрипт графиков | `title`, `variant`, `variant_summary`, `program_stdout`, `plots` |
| `section` | текст одного раздела | `title`, `sections_map`, `digest`, `section_title`, `guidance`, `forbidden`, `visuals`, `reference`, `facts`, `methodichka` |

Незаполненная подстановка остаётся в тексте как есть — шаблон не ломается. Изменения применяются
к следующему запуску; если шаг уже в кэше, укажите `from=sections` (или «С этапа» в оболочке).

## Папка работы

Имя папки может быть любым: `lab_04`, `Курсовая по сетям`, `network-course`, `зачёт`.
Номер превращается в `lab_04`, остальное используется как есть.

```
labs/lab_04/
├── Задание 4.docx        # методичка или ТЗ (PDF/DOCX/TXT) — обязательно
├── notes.txt             # ваши данные варианта, если их нет в документе
├── refs/                 # образец готового отчёта (необязательно)
│   └── пример.docx
├── src/                  # main.cpp / main.py (создаётся)
├── scripts/              # calc_and_plot.py (создаётся)
├── build/                # state.json, outline.json, sections/*.md, main.tex, main.pdf
└── reports/              # готовые report.docx, main.pdf и копии рисунков
```

Правила распознавания документов:

- **задание** — файл с `ТЗ`, `задание`, `зачёт`, `методичка`, `лаборатор…` в имени (по этому приоритету);
- **образец** — всё из подпапок `refs/`, `example/`, `образец/`, `эталон/`, а также файлы
  с именами `example*`, `sample*`, `reference*`, `образец*`, `пример*`, `готов*` в корне;
- если в папке только образец — он будет использован как задание;
- результаты самого пайплайна (`main.pdf`, `report.docx`, …) за задание не принимаются.

Вариант задаётся строкой: `--variant 1` или, если вариант составной, `--variant "i=2, j=5"`.
Дополнительные условия (матрица, номер схемы, особые требования) удобно записать в `notes.txt` —
он подмешивается в контекст.

## Команды Makefile и CLI

| Команда | Что делает |
|---|---|
| `make setup` | установить зависимости Python |
| `make new lab=04` | создать структуру `labs/lab_04/` |
| `make new name="Курсовая по сетям"` | создать папку с произвольным названием |
| `make report lab=04 variant=1` | полный цикл: PDF + DOCX |
| `make report lab=04 student="Иванов И.И." teacher="Смирнов С.С." remember=1` | без вопросов в консоли и с сохранением ФИО в `.env` |
| `make retry lab=04 from=sections` | продолжить с этапа (`extract`, `outline`, `code`, `scripts`, `sections`, `assemble`) |
| `make pdf lab=04` | пересобрать PDF без обращений к API |
| `make docx lab=04` | пересобрать Word без API |
| `make build lab=04` | оффлайн-сборка из готового `build/` |
| `make clean-lab lab=04` | очистить `build/`, `scripts/`, `src/` |
| `make gui` | графическая оболочка |
| `make app` | собрать `.app` / `.exe` через PyInstaller |
| `make test` | тесты (без расхода токенов) |

CLI напрямую (Windows и продвинутые сценарии):

```bash
python -m orchestrator.labbot.cli report labs/lab_04 --variant 1
python -m orchestrator.labbot.cli report labs/lab_04 --variant 1 --student "Иванов И.И." --teacher "Смирнов С.С."
python -m orchestrator.labbot.cli report labs/lab_04 --from-stage sections
python -m orchestrator.labbot.cli docx labs/lab_04
python -m orchestrator.labbot.cli tex labs/lab_04
```

Флаги: `--variant`, `--pages` (диапазон страниц PDF, например `3-7,9`), `--student`, `--group`,
`--teacher`, `--faculty`, `--department`, `--remember`, `--from-stage`, `--fast`.

## Что получается на выходе

| Файл | Откуда | Что это |
|---|---|---|
| `build/main.pdf` → `reports/main.pdf`, `main.pdf` | XeLaTeX | готовый отчёт |
| `build/report.docx` → `reports/report.docx`, `report.docx` | Pandoc | версия для Word со стилями ГОСТ |
| `src/main.cpp` / `src/main.py` | модель + компиляция | проверенный исходник |
| `scripts/calc_and_plot.py` | модель | скрипт графиков и таблиц |
| `flowchart.png`, `fig1.png`, … | matplotlib | блок-схема и рисунки |
| `build/sections/*.md` | модель | тексты разделов до вёрстки |
| `build/outline.json` | модель | структура, вариант, тип работы |
| `build/state.json` | пайплайн | кэш шагов |

Титульный лист подставляет `work_type`/`work_type_po` из `outline.json`: «ОТЧЕТ ПО ЗАЧЁТНОЙ РАБОТЕ №1»,
«Практическая работа №1» и т.п. Если тип не распознан — используется «Лабораторная работа».

## Сборка приложения

```bash
make app        # macOS: dist/LabBot.app; Windows: dist/LabBot/LabBot.exe
```

Внутри сборки — Python, зависимости и веб-интерфейс; отдельный Python пользователю не нужен.
При первом запуске приложение создаёт рабочую папку `~/Documents/LabBot` (там `labs/`,
`settings.json`, `.env`), путь переопределяется переменной `LABBOT_ROOT`.

- **macOS:** `make app`, затем перенести `dist/LabBot.app` в «Программы». Сборка не подписана:
  первый запуск — правый клик → «Открыть».
- **Windows:** `.exe` собирается только на Windows — `packaging\build_windows.bat` (или `make exe`).
  Кросс-компиляция PyInstaller не поддерживается, на macOS `.exe` не получить.
- **Без Windows-машины:** в репозитории есть workflow `.github/workflows/build.yml` —
  запустите его вручную (Actions → build → Run workflow), GitHub отдаст артефакты
  `LabBot-windows` и `LabBot-macos`.

## Docker

```bash
export DEEPSEEK_API_KEY=sk-...
docker compose run --rm labbot make report lab=01 variant=1
```

Образ на `python:3.11-slim` + TeX Live, Pandoc, poppler, шрифты; проект монтируется в `/app`.
Графическая оболочка рассчитана на локальный запуск, в Docker используйте CLI.

## Тесты

```bash
make test          # то же: python -m pytest -q
```

Тесты работают на моках и не тратят токены: пайплайн, поиск задания/образца, настройки и промпты,
титульный лист, HTTP API оболочки, загрузка файлов и защита от выхода за пределы папки.

## Структура репозитория

```
orchestrator/labbot/
├── cli.py        # команды report/docx/tex/build, ввод ФИО
├── gui.py        # локальный HTTP-сервер и API оболочки
├── generate.py   # пайплайн и шаги
├── prompts.py    # шаблоны промптов и подстановки
├── settings.py   # settings.json и .env
├── profile.py    # профиль исполнителя
├── extract.py    # PDF/DOCX → текст, поиск задания и образца
├── llm.py        # клиент DeepSeek, ретраи, учёт токенов
├── schemas.py    # pydantic-схемы ответа модели
├── assemble.py   # титульный лист и main.tex
├── md2tex.py     # Markdown → LaTeX
├── compile.py    # latexmk/xelatex, pandoc, стили Word
└── web/          # index.html, style.css, app.js
packaging/        # PyInstaller: entry.py, labbot.spec, build_windows.bat
tests/            # pytest
labs/             # ваши работы (не коммитятся)
```

## Безопасность и приватность

- API-ключ хранится в `.env`, который исключён из git. Не коммитьте `.env` и не публикуйте его.
- Тексты методичек, образцов и сгенерированные фрагменты отправляются в DeepSeek API.
  Не используйте инструмент для закрытых материалов.
- Отчёты и `labs/` могут содержать персональные данные — папка `labs/` тоже исключена из git.
- Локальный сервер слушает `127.0.0.1`, наружу не открывается. Авторизации нет — не запускайте
  оболочку на чужой машине и не пробрасывайте порт в интернет.
- Если ключ случайно попал в git — отзовите его в кабинете DeepSeek и создайте новый.

## Устранение неполадок

| Симптом | Причина и решение |
|---|---|
| `ModuleNotFoundError: pydantic` | запуск не тем Python: `source .venv/bin/activate` или используйте `make` (он берёт `.venv/bin/python`) |
| `latexmk: command not found` | не установлен TeX Live / MiKTeX, либо PATH: добавьте `/Library/TeX/texbin` |
| PDF не собирается, в логе `Font ... not found` | установите шрифты (`fonts-liberation`) или Times New Roman |
| DOCX не создаётся | нет Pandoc — установите и проверьте `pandoc --version` |
| `DeepSeekAPIError ... 402` | закончился баланс DeepSeek |
| `DeepSeekAPIError ... 401` | неверный ключ: проверьте `.env` или «Проверить ключ» |
| «В папке работы нет задания» | положите методичку/ТЗ в корень `labs/lab_XX/` |
| «Уже идёт генерация» | дождитесь окончания или нажмите «Остановить» |
| Порт 8765 занят | `python -m orchestrator.labbot.gui --port 8800` |
| macOS: «приложение повреждено» | сборка не подписана: правый клик → «Открыть» или `xattr -dr com.apple.quarantine dist/LabBot.app` |
| Кириллица в логе Windows «кракозябрами» | оболочка запускает подпроцесс в UTF-8; обновите версию или задайте `PYTHONIOENCODING=utf-8` |

## Лицензия

MIT — см. [LICENSE](LICENSE).
