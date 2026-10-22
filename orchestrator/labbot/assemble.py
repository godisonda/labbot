import os
import re
from datetime import date
from pathlib import Path
from typing import Dict, Optional
from .md2tex import md_to_tex
from .profile import Profile
from .schemas import LabOutline, MetaInfo

DEFAULT_WORK_TYPE = "Лабораторная работа"

# Запасные формы для типов без слова «работа», если модель не вернула work_type_po
_WORK_TYPE_PO_FALLBACK = {
    "зачёт": "ЗАЧЁТУ",
    "зачет": "ЗАЧЁТУ",
    "проект": "ПРОЕКТУ",
    "реферат": "РЕФЕРАТУ",
    "эссе": "ЭССЕ",
    "контрольная": "КОНТРОЛЬНОЙ",
    "самостоятельная": "САМОСТОЯТЕЛЬНОЙ",
}


def _report_year() -> str:
    return os.getenv("REPORT_YEAR", "").strip() or str(date.today().year)


def _sentence_case(value: str) -> str:
    """'ЛАБОРАТОРНАЯ РАБОТА' / 'лабораторная работа' → 'Лабораторная работа'."""
    text = " ".join((value or "").split())
    if not text:
        return DEFAULT_WORK_TYPE
    if text.isupper():
        text = text.lower()
    return text[0].upper() + text[1:]


def _work_type_body(meta: MetaInfo) -> str:
    return _sentence_case(meta.work_type)


def _work_type_po(meta: MetaInfo) -> str:
    """Форма после «ПО»: 'ЛАБОРАТОРНОЙ РАБОТЕ'.

    Если модель не заполнила work_type_po, выводим из work_type для шаблона
    «… работа»; для остальных типов просто поднимаем регистр.
    """
    explicit = " ".join((meta.work_type_po or "").split())
    if explicit:
        return explicit.upper()

    words = _work_type_body(meta).lower().split()
    if len(words) == 1 and words[0] in _WORK_TYPE_PO_FALLBACK:
        return _WORK_TYPE_PO_FALLBACK[words[0]]
    if len(words) >= 2 and words[-1] in ("работа", "работы"):
        words[-1] = "работе"
        adjective = words[-2]
        if adjective.endswith("ая"):
            words[-2] = adjective[:-2] + "ой"
        elif adjective.endswith("яя"):
            words[-2] = adjective[:-2] + "ей"
    return " ".join(word.upper() for word in words)


def _signature_tex(profile: Profile) -> str:
    """Блок «Выполнил / Проверил». Пустые поля просто не печатаются."""
    parts = []
    if profile.student:
        head = f"Выполнил: ст. гр. {profile.group}" if profile.group else "Выполнил:"
        parts.append(f"{head}\\\\\n{profile.student}")
    if profile.teacher:
        parts.append(f"Проверил: {profile.teacher}")
    return "\n\n\\vspace{1em}\n".join(parts)


def _signature_md(profile: Profile) -> str:
    lines = []
    if profile.student:
        head = f"Выполнил: ст. гр. {profile.group}" if profile.group else "Выполнил:"
        lines.append(f"{head} {profile.student}")
    if profile.teacher:
        lines.append(f"Проверил: {profile.teacher}")
    return "\n".join(lines)


def sanitize_section_for_word(content: str, title: str) -> str:
    lines = content.splitlines()
    if not lines:
        return ""

    clean_title = re.sub(r"^\d+[\.\s]+", "", title).strip().lower()
    if lines and (lines[0].strip().startswith("#") or clean_title in lines[0].strip().lower()):
        lines = lines[1:]

    text = "\n".join(lines).strip()

    # Форматирование блоков скриншотов в Word
    def repl_screenshot(m):
        body = m.group(1).strip()
        quote_lines = [f"> {line}" for line in body.splitlines()]
        return "\n\n> **[ПОЛЕ РЕАЛИЗАЦИИ ЗАДАНИЯ / СКРИНШОТ]**\n" + "\n".join(quote_lines) + "\n\n"

    text = re.sub(r":::(?:screenshot|placeholder)\s*(.*?)\s*:::", repl_screenshot, text, flags=re.DOTALL)

    # Исправляем любые поврежденные таблицы Markdown перед компиляцией в Word
    lines = text.splitlines()
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if "|" in stripped and not stripped.startswith("```"):
            tbl_lines = []
            while i < len(lines) and "|" in lines[i].strip() and not lines[i].strip().startswith("```"):
                tbl_lines.append(lines[i].strip())
                i += 1

            parsed_rows = []
            for tl in tbl_lines:
                cells = [c.strip() for c in tl.strip("|").split("|")]
                is_sep = all(set(c).issubset({"-", "—", "–", ":", " "}) and len(c) > 0 for c in cells)
                parsed_rows.append((cells, is_sep))

            if parsed_rows:
                max_c = max(len(r[0]) for r in parsed_rows)
                out.append("")
                header = parsed_rows[0][0] + [""] * (max_c - len(parsed_rows[0][0]))
                out.append("| " + " | ".join(header) + " |")
                out.append("| " + " | ".join([":---"] * max_c) + " |")
                start = 2 if len(parsed_rows) > 1 and parsed_rows[1][1] else 1
                for r_cells, is_sep in parsed_rows[start:]:
                    if not is_sep:
                        padded = r_cells + [""] * (max_c - len(r_cells))
                        out.append("| " + " | ".join(padded) + " |")
                out.append("")
        else:
            out.append(line)
            i += 1

    return "\n".join(out)


def assemble_report_tex(
    lab_dir: Path,
    outline: LabOutline,
    sections: Dict[str, str],
    profile: Optional[Profile] = None,
) -> Path:
    build_dir = lab_dir / "build"
    build_dir.mkdir(parents=True, exist_ok=True)
    main_tex = build_dir / "main.tex"
    word_md = build_dir / "report_for_word.md"
    combined_md = build_dir / "report_combined.md"

    profile = profile or Profile.from_env()
    faculty = profile.faculty or "ИТ"
    department = (
        outline.meta.department
        or profile.department
        or "Кафедра информатики и вычислительной техники"
    )
    discipline = outline.meta.discipline or "Информатика и программирование (ИТиП)"
    year = _report_year()
    work_type = _work_type_body(outline.meta)
    work_type_po = _work_type_po(outline.meta)
    signature_tex = _signature_tex(profile)
    signature_md = _signature_md(profile)

    # Фильтруем "Титульный лист" из разделов
    clean_sections = [s for s in outline.sections if not any(w in s.title.lower() for w in ["титул", "титульный"])]

    # 1. Сборка LaTeX main.tex
    body_tex = []
    body_tex.append(
        f"\\begin{{center}}\n"
        f"  {{\\large\\bfseries {work_type} №{outline.meta.number}}}\\\\[0.3em]\n"
        f"  {{\\large\\bfseries «{outline.meta.title}»}}\n"
        f"\\end{{center}}\n\\vspace{{1.2em}}"
    )

    for sec in clean_sections:
        raw_c = sections.get(sec.id, "")
        clean_c = sanitize_section_for_word(raw_c, sec.title)
        sec_tex = md_to_tex(clean_c)
        clean_title = re.sub(r"^\d+[\.\s]+", "", sec.title).strip()
        body_tex.append(f"\\section{{{clean_title}}}\n{sec_tex}\n")

    full_body_tex = "\n\\vspace{1.2em}\n".join(body_tex)

    tex_document = f"""\\documentclass[a4paper,12pt]{{article}}
\\usepackage{{fontspec}}
\\usepackage[russian]{{babel}}
\\IfFontExistsTF{{Times New Roman}}{{
  \\setmainfont{{Times New Roman}}
}}{{
  \\IfFontExistsTF{{Liberation Serif}}{{
    \\setmainfont{{Liberation Serif}}
  }}{{}}
}}
\\IfFontExistsTF{{Courier New}}{{
  \\setmonofont{{Courier New}}
}}{{
  \\IfFontExistsTF{{Menlo}}{{
    \\setmonofont{{Menlo}}
  }}{{}}
}}
\\usepackage[left=25mm,right=15mm,top=20mm,bottom=20mm]{{geometry}}
\\usepackage{{amsmath,amssymb}}
\\usepackage{{graphicx}}
\\usepackage{{listings}}
\\usepackage{{xcolor}}
\\usepackage{{setspace}}
\\singlespacing
\\usepackage{{indentfirst}}
\\setlength{{\\parindent}}{{1.0cm}}
\\usepackage{{hyperref}}
\\usepackage{{tabularx}}
\\usepackage{{booktabs}}
\\usepackage{{float}}
\\usepackage{{caption}}
\\DeclareCaptionLabelSeparator{{endash}}{{\\space---\\space}}
\\captionsetup[figure]{{name=Рисунок,labelsep=endash}}
\\captionsetup[table]{{name=Таблица,labelsep=endash}}
\\sloppy

\\lstset{{
  basicstyle=\\ttfamily\\small,
  breaklines=true,
  frame=single,
  showstringspaces=false
}}

\\begin{{document}}

\\begin{{titlepage}}
\\begin{{center}}
  {{\\small МИНИСТЕРСТВО ЦИФРОВОГО РАЗВИТИЯ, СВЯЗИ И МАССОВЫХ КОММУНИКАЦИЙ РОССИЙСКОЙ ФЕДЕРАЦИИ}}\\\\[0.5em]
  {{\\small ОРДЕНА ТРУДОВОГО КРАСНОГО ЗНАМЕНИ ФЕДЕРАЛЬНОЕ ГОСУДАРСТВЕННОЕ БЮДЖЕТНОЕ ОБРАЗОВАТЕЛЬНОЕ УЧРЕЖДЕНИЕ ВЫСШЕГО ОБРАЗОВАНИЯ}}\\\\[0.5em]
  {{\\bfseries МОСКОВСКИЙ ТЕХНИЧЕСКИЙ УНИВЕРСИТЕТ СВЯЗИ И ИНФОРМАТИКИ}}\\\\[1.5em]
  Факультет «{faculty}»\\\\
  Кафедра «{department}»\\\\[2.5em]

  {{\\normalsize Дисциплина: «{discipline}»}}\\\\[1.5em]

  {{\\large\\bfseries ОТЧЕТ ПО {work_type_po} №{outline.meta.number}}}\\\\[0.8em]
  {{\\large «{outline.meta.title}»}}\\\\[4em]
\\end{{center}}

\\begin{{flushright}}
  \\begin{{minipage}}{{0.55\\textwidth}}
    {signature_tex}
  \\end{{minipage}}
\\end{{flushright}}

\\vfill

\\begin{{center}}
  Москва, {year}
\\end{{center}}
\\end{{titlepage}}

\\newpage
{full_body_tex}

\\end{{document}}
"""
    main_tex.write_text(tex_document, encoding="utf-8")

    # 2. Сборка для Word (.docx)
    word_content = [
        "МИНИСТЕРСТВО ЦИФРОВОГО РАЗВИТИЯ, СВЯЗИ И МАССОВЫХ КОММУНИКАЦИЙ РОССИЙСКОЙ ФЕДЕРАЦИИ\n",
        "ОРДЕНА ТРУДОВОГО КРАСНОГО ЗНАМЕНИ ФЕДЕРАЛЬНОЕ ГОСУДАРСТВЕННОЕ БЮДЖЕТНОЕ ОБРАЗОВАТЕЛЬНОЕ УЧРЕЖДЕНИЕ ВЫСШЕГО ОБРАЗОВАНИЯ\n",
        "**МОСКОВСКИЙ ТЕХНИЧЕСКИЙ УНИВЕРСИТЕТ СВЯЗИ И ИНФОРМАТИКИ**\n",
        f"**Факультет «{faculty}»**\n",
        f"**Кафедра «{department}»**\n\n",
        f"Дисциплина: «{discipline}»\n\n",
        f"# ОТЧЕТ ПО {work_type_po} №{outline.meta.number}\n",
        f"## «{outline.meta.title}»\n\n",
        (signature_md + "\n\n") if signature_md else "",
        f"Москва, {year}\n\n",
        f"# {work_type} №{outline.meta.number}. «{outline.meta.title}»\n"
    ]

    clean_md_content = [
        f"# {work_type} №{outline.meta.number}\n## {outline.meta.title}\n"
    ]

    for sec in clean_sections:
        raw_c = sections.get(sec.id, "")
        clean_c = sanitize_section_for_word(raw_c, sec.title)
        sec_header = f"\n# {sec.title}\n\n"
        word_content.append(sec_header + clean_c + "\n")
        clean_md_content.append(sec_header + clean_c + "\n")

    word_md.write_text("\n".join(word_content), encoding="utf-8")
    combined_md.write_text("\n".join(clean_md_content), encoding="utf-8")

    return main_tex
