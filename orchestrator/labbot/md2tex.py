import re
from pathlib import Path


def _is_separator_row(line: str) -> bool:
    cleaned = line.strip().replace(" ", "").replace("|", "")
    return len(cleaned) > 0 and all(c in "-—–:+" for c in cleaned)


def _is_markdown_table_row(s: str) -> bool:
    """Строка является строкой таблицы ТОЛЬКО если она начинается и заканчивается на '|' и имеет >= 2 ячеек."""
    if not s or s.startswith("```") or s.startswith("$") or "||" in s:
        return False
    return s.startswith("|") and s.endswith("|") and s.count("|") >= 3


def _clean_caption(caption: str, prefix: str) -> str:
    cleaned = re.sub(rf"^(?:{prefix})\s*\d*[\s.:—–-]*", "", caption, flags=re.IGNORECASE).strip()
    return cleaned if cleaned else caption


def _convert_table(table_lines, caption: str = "") -> str:
    rows = []
    for line in table_lines:
        line = line.strip()
        if not line or _is_separator_row(line):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        rows.append(cells)

    if not rows:
        return ""

    num_cols = max(len(r) for r in rows)
    col_spec = "|" + "c|" * num_cols

    tex = ["\\begin{table}[H]", "\\centering"]
    if caption:
        clean_cap = _clean_caption(caption, "Таблица")
        tex.append(f"\\caption{{{_format_inline(clean_cap)}}}")
        tex.append("\\vspace{0.4em}")

    use_resize = num_cols >= 4
    if use_resize:
        tex.append("\\resizebox{\\textwidth}{!}{%")

    tex.append(f"\\begin{{tabular}}{{{col_spec}}}")
    tex.append("\\hline")

    for row_idx, row in enumerate(rows):
        padded = row + [""] * (num_cols - len(row))
        formatted_cells = []
        is_header = row_idx == 0
        for val in padded:
            cell_text = _format_inline(val)
            if is_header and val:
                formatted_cells.append(f"\\textbf{{{cell_text}}}")
            else:
                formatted_cells.append(cell_text)

        row_tex = " & ".join(formatted_cells) + " \\\\ \\hline"
        tex.append(row_tex)

    tex.append("\\end{tabular}")
    if use_resize:
        tex.append("}%")
    tex.append("\\end{table}")
    return "\n".join(tex)


def md_to_tex(md_content: str) -> str:
    lines = md_content.splitlines()
    out = []
    in_code_block = False
    in_itemize = False
    in_enumerate = False
    in_manual_box = False
    manual_box_lines = []
    table_buffer = []
    table_caption = ""
    is_first_line = True

    for line in lines:
        stripped = line.strip()

        if stripped.startswith(":::screenshot") or stripped.startswith(":::placeholder"):
            in_manual_box = True
            manual_box_lines = []
            continue
        elif stripped == ":::" and in_manual_box:
            in_manual_box = False
            box_text = "\\\\\n".join([_format_inline(l) for l in manual_box_lines if l.strip()])
            out.append(
                "\\vspace{0.5em}\n\\begin{center}\n"
                "\\fbox{\\parbox{0.92\\textwidth}{\\small\\textbf{Поле реализации задания / Скриншот:}\\\\[0.4em]\n"
                f"{box_text}\n"
                "}}\n\\end{center}\n\\vspace{0.5em}"
            )
            continue

        if in_manual_box:
            manual_box_lines.append(stripped)
            continue

        if stripped.startswith("```"):
            if table_buffer:
                out.append(_convert_table(table_buffer, table_caption))
                table_buffer = []
                table_caption = ""
            if in_enumerate:
                out.append("\\end{enumerate}")
                in_enumerate = False
            if in_itemize:
                out.append("\\end{itemize}")
                in_itemize = False

            if not in_code_block:
                in_code_block = True
                out.append("\\begin{lstlisting}[breaklines=true,basicstyle=\\ttfamily\\small,frame=single,showstringspaces=false]")
            else:
                in_code_block = False
                out.append("\\end{lstlisting}")
            continue

        if in_code_block:
            out.append(line)
            continue

        if is_first_line and (stripped.startswith("#") or re.match(r"^\d+\.?\s+[А-Яа-я]", stripped)):
            is_first_line = False
            continue
        if stripped:
            is_first_line = False

        if in_enumerate and (stripped.startswith("#") or _is_markdown_table_row(stripped) or stripped.startswith("![")):
            out.append("\\end{enumerate}")
            in_enumerate = False
        if in_itemize and (stripped.startswith("#") or _is_markdown_table_row(stripped) or stripped.startswith("![")):
            out.append("\\end{itemize}")
            in_itemize = False

        img_match = re.match(r"^!\[(.*?)\]\s*\((.*?)\)$", stripped)
        if img_match:
            if table_buffer:
                out.append(_convert_table(table_buffer, table_caption))
                table_buffer = []
                table_caption = ""
            caption, img_path = img_match.groups()
            img_file = Path(img_path).name
            clean_cap = _clean_caption(caption, "Рис\\.?|Рисунок")
            out.append("\\begin{figure}[H]")
            out.append("\\centering")
            out.append(f"\\IfFileExists{{{img_file}}}{{\\includegraphics[width=0.68\\textwidth]{{{img_file}}}}}{{\\fbox{{[Изображение: {img_file}]}}}}")
            if clean_cap:
                out.append(f"\\caption{{{_format_inline(clean_cap)}}}")
            out.append("\\end{figure}")
            continue

        if stripped.lower().startswith("таблица ") and any(c in stripped for c in ["—", "-", ":"]):
            table_caption = stripped
            continue

        if _is_markdown_table_row(stripped):
            table_buffer.append(stripped)
            continue
        elif table_buffer:
            out.append(_convert_table(table_buffer, table_caption))
            table_buffer = []
            table_caption = ""

        num_match = re.match(r"^(\d+)\.\s+(.*)", stripped)
        if num_match:
            if not in_enumerate:
                if in_itemize:
                    out.append("\\end{itemize}")
                    in_itemize = False
                out.append("\\begin{enumerate}")
                in_enumerate = True
            item_text = _format_inline(num_match.group(2))
            out.append(f"  \\item \\textbf{{{item_text}}}")
            continue

        if stripped.startswith("- ") or stripped.startswith("* "):
            if not in_itemize:
                if in_enumerate:
                    out.append("\\end{enumerate}")
                    in_enumerate = False
                out.append("\\begin{itemize}")
                in_itemize = True
            item_text = stripped[2:].strip()
            out.append(f"  \\item {_format_inline(item_text)}")
            continue

        if in_enumerate:
            if stripped:
                out.append(f"  {_format_inline(stripped)}\\par")
            continue

        if stripped.startswith("### "):
            out.append(f"\\subsubsection*{{{_format_inline(stripped[4:])}}}")
        elif stripped.startswith("## "):
            out.append(f"\\subsection*{{{_format_inline(stripped[3:])}}}")
        elif stripped.startswith("# "):
            out.append(f"\\subsection*{{{_format_inline(stripped[2:])}}}")
        else:
            if stripped:
                out.append(_format_inline(line))
            else:
                out.append("")

    if table_buffer:
        out.append(_convert_table(table_buffer, table_caption))
    if in_itemize:
        out.append("\\end{itemize}")
    if in_enumerate:
        out.append("\\end{enumerate}")
    if in_code_block:
        out.append("\\end{lstlisting}")

    return "\n".join(out)


def _format_inline(text: str) -> str:
    math_tokens = []

    def save_math(match):
        token = f"@@MATH{len(math_tokens)}@@"
        m = match.group(0)
        m = m.replace(r"\_", "_").replace(r"\%", "%").replace(r"\&", "&")
        def repl_cyr(cm):
            full = cm.group(0)
            if full.startswith(r"\text{"):
                return full
            return f"\\text{{{full}}}"
        m = re.sub(r"\\text\{[а-яА-ЯёЁ\s,.-]+\}|[а-яА-ЯёЁ]+", repl_cyr, m)
        math_tokens.append(m)
        return token

    text = re.sub(r"\$\$.*?\$\$", save_math, text, flags=re.DOTALL)
    text = re.sub(r"\$.*?\$", save_math, text)

    code_tokens = []

    def save_code(match):
        token = f"@@CODE{len(code_tokens)}@@"
        c = match.group(1).replace("\\", r"\textbackslash{}")
        for ch in ["%", "&", "#", "_", "{", "}"]:
            c = c.replace(ch, f"\\{ch}")
        code_tokens.append(f"\\texttt{{{c}}}")
        return token

    text = re.sub(r"`(.*?)`", save_code, text)

    text = text.replace(r"\_", "_").replace(r"\%", "%").replace(r"\&", "&").replace(r"\#", "#")
    text = text.replace("\\", r"\textbackslash{}")

    text = re.sub(r"\*\*(.*?)\*\*", r"\\textbf{\1}", text)
    text = re.sub(r"\*(.*?)\*", r"\\textit{\1}", text)

    for ch in ["%", "&", "#", "_"]:
        text = text.replace(ch, f"\\{ch}")
    text = text.replace("^", r"\^{}").replace("~", r"\~{}")

    for i, token in enumerate(code_tokens):
        text = text.replace(f"@@CODE{i}@@", token)
    for i, token in enumerate(math_tokens):
        text = text.replace(f"@@MATH{i}@@", token)

    return text
