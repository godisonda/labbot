from typing import List, Optional
from pydantic import BaseModel, Field


class FlowchartStep(BaseModel):
    text: str = Field(..., description="Краткий текст внутри блока (до 2-3 строк)")
    shape: str = Field(
        default="rect",
        description="Форма блока по ГОСТ: 'oval' (начало/конец), 'rect' (процесс/действие), 'diamond' (условие), 'io' (ввод/вывод)"
    )


class FlowchartChain(BaseModel):
    title: str = Field(..., description="Название алгоритма")
    steps: List[FlowchartStep] = Field(..., description="Последовательность шагов алгоритма от Начала до Конца")


class VisualItem(BaseModel):
    id: str = Field(..., description="ID иллюстрации: fig1, fig2 и т.д.")
    title: str = Field(..., description="Подпись к рисунку по ГОСТ")
    visual_type: str = Field(
        ...,
        description="Тип: 'plot' (график/гистограмма), 'schematic' (схема цепи), 'screenshot' (окно консоли/программы)"
    )
    can_python_render: bool = Field(
        ...,
        description="True для графиков и диаграмм (matplotlib), False для скриншотов окон и внешних САПР"
    )
    target_section_id: str = Field(
        ...,
        description="ID единственного раздела отчета, в который должен быть вставлен этот рисунок"
    )
    generation_prompt: Optional[str] = Field(default="", description="Промпт на английском для генерации скриншота")
    software_instructions: Optional[str] = Field(default="", description="Пошаговая инструкция получения скриншота в ПО")


class MetaInfo(BaseModel):
    number: str = Field(default="1", description="Номер работы из методички")
    work_type: str = Field(
        default="Лабораторная работа",
        description=(
            "Тип работы в именительном падеже, как в методичке: 'Лабораторная работа', "
            "'Практическая работа', 'Зачётная работа', 'Контрольная работа', 'Курсовая работа', "
            "'Расчётно-графическая работа', 'Зачёт', 'Проект', 'Реферат'"
        ),
    )
    work_type_po: str = Field(
        default="",
        description=(
            "Тот же тип работы в форме после слова «ПО» — для титульного листа: "
            "'ЛАБОРАТОРНОЙ РАБОТЕ', 'ПРАКТИЧЕСКОЙ РАБОТЕ', 'ЗАЧЁТНОЙ РАБОТЕ', 'КУРСОВОЙ РАБОТЕ'. "
            "Если тип не содержит слова «работа» — 'ЗАЧЁТУ', 'ПРОЕКТУ', 'РЕФЕРАТУ'"
        ),
    )
    discipline: str = Field(default="", description="Название учебной дисциплины")
    department: str = Field(default="", description="Кафедра")
    title: str = Field(default="", description="Точная тема работы")
    goal: str = Field(default="", description="Цель работы")
    variant_summary: str = Field(
        default="",
        description="Точные параметры выбранного варианта, извлеченные из таблиц методички"
    )
    software_stack: List[str] = Field(default_factory=list, description="Используемое ПО и языки программирования")
    has_mathcad: bool = Field(default=False, description="True ТОЛЬКО если в методичке прямо требуется Mathcad")
    has_source_code: bool = Field(default=True, description="True если работа требует написания кода на C++/Python и т.д.")
    code_language: str = Field(default="cpp", description="Язык кода для листинга: cpp, python, c и т.д.")


class SectionSpec(BaseModel):
    id: str = Field(..., description="Уникальный ID раздела (task, algo, listing, test, results, conclusion)")
    title: str = Field(..., description="Заголовок раздела с номером")
    guidance: str = Field(..., description="Что именно должно быть в этом разделе")
    forbidden_content: str = Field(
        default="",
        description="Чего категорически НЕ должно быть в этом разделе во избежание дублирования с соседними разделами"
    )


class LabOutline(BaseModel):
    meta: MetaInfo
    flowcharts: List[FlowchartChain] = Field(
        default_factory=list,
        description="Логические цепочки блок-схем алгоритмов работы (если в работе есть алгоритмы)"
    )
    visuals: List[VisualItem] = Field(default_factory=list, description="Список графиков и скриншотов")
    sections: List[SectionSpec] = Field(..., description="Разделы отчета строго по методичке")
