# Работа: номер (lab=05 → labs/lab_05) или произвольное имя
# (name="Курсовая по сетям" → labs/Курсовая по сетям).
ifdef lab
  override LAB := $(lab)
endif
LAB ?= 05

# Произвольное название папки; важнее номера
ifdef name
  override NAME := $(name)
endif
NAME ?=

# Интерпретатор: сначала venv проекта, иначе системный python3
PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

FROM ?= sections
PAGES ?=
VARIANT ?= $(or $(variant),)

# Данные титульного листа. Не заданы — будут спрошены в консоли.
student ?=
teacher ?=
group ?=
remember ?=

PROFILE_FLAGS := $(if $(student),--student "$(student)",) $(if $(group),--group "$(group)",) $(if $(teacher),--teacher "$(teacher)",) $(if $(remember),--remember,)

LAB_DIR := $(if $(NAME),labs/$(NAME),$(if $(filter lab_%,$(LAB)),labs/$(LAB),labs/lab_$(LAB)))

.PHONY: help setup new report retry docx pdf build clean-lab clean sanity test gui app exe

help:
	@echo "LabBot — генерация отчётов"
	@echo "  make new lab=05                       — создать labs/lab_05"
	@echo "  make new name=\"Курсовая по сетям\"      — создать папку с любым названием"
	@echo "  make report lab=05                    — сгенерировать отчёт (PDF + Word)"
	@echo "  make report name=\"Курсовая\" variant=1  — то же для работы по имени"
	@echo "  make retry lab=05                     — пересборка с этапа разделов"
	@echo "  make clean-lab lab=05                 — сбросить кэш работы"
	@echo "  make gui                              — графическая оболочка"
	@echo "  make app                              — собрать приложение (.app / .exe)"
	@echo ""
	@echo "  ФИО: make report lab=05 student=\"Иванов И.И.\" teacher=\"Смирнов С.С.\""
	@echo "  Запомнить: make report lab=05 remember=1"
	@echo "  Образец: положите файл в labs/lab_05/refs/ (или назовите example*/образец*)"

setup:
	$(PYTHON) -m pip install -r requirements.txt

new:
	@mkdir -p "$(LAB_DIR)/build" "$(LAB_DIR)/reports" "$(LAB_DIR)/scripts" "$(LAB_DIR)/src" "$(LAB_DIR)/refs"
	@echo "Создана директория $(LAB_DIR). Методичку/ТЗ положите в корень, образец — в $(LAB_DIR)/refs/."

report: sanity
	$(PYTHON) -m orchestrator.labbot.cli report "$(LAB_DIR)" $(if $(VARIANT),--variant "$(VARIANT)",) $(if $(PAGES),--pages "$(PAGES)",) $(PROFILE_FLAGS)

retry: sanity
	$(PYTHON) -m orchestrator.labbot.cli report "$(LAB_DIR)" --from-stage "$(FROM)" $(if $(VARIANT),--variant "$(VARIANT)",) $(if $(PAGES),--pages "$(PAGES)",) $(PROFILE_FLAGS)

docx:
	$(PYTHON) -m orchestrator.labbot.cli docx "$(LAB_DIR)"

pdf:
	$(PYTHON) -m orchestrator.labbot.cli tex "$(LAB_DIR)"

build:
	$(PYTHON) -m orchestrator.labbot.cli build "$(LAB_DIR)"

clean-lab:
	rm -rf "$(LAB_DIR)/build/"* "$(LAB_DIR)/scripts/"* "$(LAB_DIR)/src/"*

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find labs/ -type d -name "build" -exec rm -rf {}/* +

sanity:
	$(PYTHON) -m orchestrator.labbot.cli sanity

gui:
	$(PYTHON) -m orchestrator.labbot.gui

app:
	$(PYTHON) -m pip install pyinstaller
	$(PYTHON) -m PyInstaller packaging/labbot.spec --noconfirm --clean
	@echo "Готово: dist/LabBot.app (macOS) или dist/LabBot/LabBot.exe (Windows)"

exe: app

test:
	$(PYTHON) -m pytest -q
