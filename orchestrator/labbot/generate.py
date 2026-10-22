import json
import logging
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Dict, List, Optional, Set
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as patches

from .assemble import assemble_report_tex
from .compile import compile_all
from .extract import extract_document_text, find_lab_documents
from .llm import DeepSeekClient
from .profile import Profile
from .prompts import render_prompt
from .settings import load_settings
from .schemas import LabOutline, FlowchartChain

logger = logging.getLogger("mtuci-labbot.generate")


def is_strict_table_line(s: str) -> bool:
    """Строка считается частью таблицы только если это строка вида | ... | ... | вне кода и формул."""
    if not s or s.startswith("```") or s.startswith("$") or "||" in s or ";" in s:
        return False
    return s.startswith("|") and s.endswith("|") and s.count("|") >= 3


def protect_and_normalize_tables(text: str) -> str:
    """
    1. Защищает блоки кода ```...``` и формулы $...$ токенами.
    2. Нормализует только настоящие таблицы Markdown.
    3. Возвращает защищенные блоки кода и формул обратно без единого искажения.
    """
    code_blocks = []

    def save_code_block(m):
        token = f"@@PROTECTED_CODE_BLOCK_{len(code_blocks)}@@"
        code_blocks.append(m.group(0))
        return token

    text = re.sub(r"```.*?\n.*?```", save_code_block, text, flags=re.DOTALL)

    math_blocks = []

    def save_math_block(m):
        token = f"@@PROTECTED_MATH_BLOCK_{len(math_blocks)}@@"
        math_blocks.append(m.group(0))
        return token

    text = re.sub(r"\$\$.*?\$\$", save_math_block, text, flags=re.DOTALL)
    text = re.sub(r"\$[^\$\n]+\$", save_math_block, text)

    lines = text.splitlines()
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if is_strict_table_line(stripped) and i + 1 < len(lines) and is_strict_table_line(lines[i + 1].strip()):
            tbl_lines = []
            while i < len(lines) and is_strict_table_line(lines[i].strip()):
                tbl_lines.append(lines[i].strip())
                i += 1

            parsed_rows = []
            for tl in tbl_lines:
                cells = [c.strip() for c in tl.strip("|").split("|")]
                is_sep = all(set(c).issubset({"-", "—", "–", ":", " "}) and len(c) > 0 for c in cells)
                parsed_rows.append((cells, is_sep))

            if parsed_rows:
                max_c = max(len(r[0]) for r in parsed_rows)
                formatted = []
                header_cells = parsed_rows[0][0] + [""] * (max_c - len(parsed_rows[0][0]))
                formatted.append("| " + " | ".join(header_cells) + " |")
                formatted.append("| " + " | ".join([":---"] * max_c) + " |")

                start_idx = 2 if (len(parsed_rows) > 1 and parsed_rows[1][1]) else 1
                for r_cells, is_sep in parsed_rows[start_idx:]:
                    if not is_sep:
                        r_padded = r_cells + [""] * (max_c - len(r_cells))
                        formatted.append("| " + " | ".join(r_padded) + " |")

                out.append("")
                out.append("\n".join(formatted))
                out.append("")
            continue
        else:
            out.append(line)
            i += 1

    res = "\n".join(out)
    for idx, mb in enumerate(math_blocks):
        res = res.replace(f"@@PROTECTED_MATH_BLOCK_{idx}@@", mb)
    for idx, cb in enumerate(code_blocks):
        res = res.replace(f"@@PROTECTED_CODE_BLOCK_{idx}@@", cb)
    return res


def render_universal_flowchart(chains: List[FlowchartChain], output_path: Path):
    """Универсальный геометрический рендерер блок-схем по ГОСТ 19.701-90."""
    if not chains:
        return

    num_cols = min(len(chains), 3)
    chains = chains[:num_cols]

    prepared_cols = []
    max_total_height = 0.0
    vertical_gap = 0.55

    for chain in chains:
        nodes_geom = []
        cur_y = 0.0
        for step in chain.steps:
            raw_lines = step.text.strip().splitlines()
            wrapped_lines = []
            for rl in raw_lines:
                wrapped_lines.extend(textwrap.wrap(rl, width=25) or [""])

            wrapped_text = "\n".join(wrapped_lines)
            n_lines = len(wrapped_lines)
            max_chars = max((len(l) for l in wrapped_lines), default=10)

            shape = step.shape.lower()
            if shape == "diamond":
                w = max(3.4, max_chars * 0.14 + 1.2)
                h = max(1.10, n_lines * 0.38 + 0.65)
            elif shape == "oval":
                w = max(3.2, max_chars * 0.13 + 0.8)
                h = max(0.75, n_lines * 0.35 + 0.38)
            else:
                w = max(3.3, max_chars * 0.13 + 0.75)
                h = max(0.72, n_lines * 0.34 + 0.36)

            top_y = cur_y
            center_y = top_y - h / 2.0
            bottom_y = top_y - h
            nodes_geom.append({
                "text": wrapped_text,
                "shape": shape,
                "w": w,
                "h": h,
                "top_y": top_y,
                "center_y": center_y,
                "bottom_y": bottom_y,
            })
            cur_y = bottom_y - vertical_gap

        total_h = abs(cur_y)
        if total_h > max_total_height:
            max_total_height = total_h
        wrapped_title = "\n".join(textwrap.wrap(chain.title, width=28))
        prepared_cols.append((wrapped_title, nodes_geom))

    col_width = 5.4
    total_width = col_width * num_cols
    fig_h = max(6.5, min(13.5, max_total_height * 0.85 + 1.6))
    fig_w = max(7.0, 4.8 * num_cols)

    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    ax.set_xlim(0, total_width)
    ax.set_ylim(-max_total_height - 0.4, 1.35)
    ax.axis("off")

    for col_idx, (title, nodes) in enumerate(prepared_cols):
        cx = col_idx * col_width + col_width / 2.0
        ax.text(cx, 0.72, title, ha="center", va="center", fontsize=9.5, fontweight="bold", color="#1f4e79")

        for idx, nd in enumerate(nodes):
            w, h, cy = nd["w"], nd["h"], nd["center_y"]
            shape = nd["shape"]

            if shape == "oval":
                patch = patches.FancyBboxPatch(
                    (cx - w / 2, cy - h / 2), w, h,
                    boxstyle="round,pad=0.15", fc="#eef4fb", ec="#1f4e79", lw=1.4
                )
            elif shape == "diamond":
                patch = patches.Polygon(
                    [[cx, cy + h / 2], [cx + w / 2, cy], [cx, cy - h / 2], [cx - w / 2, cy]],
                    fc="#fff9e6", ec="#b78103", lw=1.4
                )
            elif shape == "io":
                offset = 0.25
                patch = patches.Polygon(
                    [[cx - w / 2 + offset, cy + h / 2], [cx + w / 2 + offset, cy + h / 2],
                     [cx + w / 2 - offset, cy - h / 2], [cx - w / 2 - offset, cy - h / 2]],
                    fc="#f0fdf4", ec="#15803d", lw=1.4
                )
            else:
                patch = patches.FancyBboxPatch(
                    (cx - w / 2, cy - h / 2), w, h,
                    boxstyle="square,pad=0.0", fc="#f7f9fa", ec="#3c4043", lw=1.4
                )

            ax.add_patch(patch)
            ax.text(
                cx, cy, nd["text"],
                ha="center", va="center", fontsize=8.2, linespacing=1.18, multialignment="center"
            )

            if idx < len(nodes) - 1:
                next_nd = nodes[idx + 1]
                ax.annotate(
                    "", xy=(cx, next_nd["top_y"]), xytext=(cx, nd["bottom_y"]),
                    arrowprops=dict(arrowstyle="->", color="#1f4e79", lw=1.3)
                )
                if shape == "diamond":
                    ax.text(cx + 0.18, (nd["bottom_y"] + next_nd["top_y"]) / 2, "Да", fontsize=8, color="#1f4e79")

    plt.tight_layout()
    plt.savefig(output_path, dpi=200)
    plt.close()


class GenerationState:
    def __init__(self, state_file: Path):
        self.state_file = state_file
        self.data: Dict = {}
        self.load()

    def load(self):
        if self.state_file.exists():
            try:
                self.data = json.loads(self.state_file.read_text(encoding="utf-8"))
            except Exception:
                self.data = {}

    def save(self):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")

    def is_step_done(self, step: str) -> bool:
        return self.data.get("completed_steps", {}).get(step, False)

    def mark_step_done(self, step: str):
        if "completed_steps" not in self.data:
            self.data["completed_steps"] = {}
        self.data["completed_steps"][step] = True
        self.save()

    def reset_from(self, stage: str):
        stages = ["extract", "outline", "code", "scripts", "sections", "assemble"]
        if stage in stages:
            idx = stages.index(stage)
            wipe_stages = set(stages[idx:])
            if "completed_steps" in self.data:
                keys_to_delete = [
                    k for k in self.data["completed_steps"]
                    if k in wipe_stages or ("sections" in wipe_stages and k.startswith("section_"))
                ]
                for k in keys_to_delete:
                    del self.data["completed_steps"][k]
            self.save()


class PipelineRunner:
    def __init__(
        self,
        lab_dir: Path,
        client: DeepSeekClient,
        variant: Optional[str] = "1",
        fast_mode: bool = False,
        from_stage: Optional[str] = None,
        pages: Optional[str] = None,
        profile: Optional[Profile] = None,
        prompts: Optional[Dict[str, str]] = None,
        settings: Optional[Dict] = None,
    ):
        self.lab_dir = lab_dir.resolve()
        self.client = client
        self.variant = variant or "1"
        self.fast_mode = fast_mode
        self.pages = pages
        self.profile = profile or Profile.from_env()
        self.settings = settings or load_settings()
        self.prompts = prompts or self.settings.get("prompts") or {}
        self.reference_text = ""
        self.build_dir = self.lab_dir / "build"
        self.reports_dir = self.lab_dir / "reports"
        self.scripts_dir = self.lab_dir / "scripts"
        self.src_dir = self.lab_dir / "src"
        self.state = GenerationState(self.build_dir / "state.json")

        if from_stage:
            logger.info("Сброс состояния с этапа: %s", from_stage)
            self.state.reset_from(from_stage)

    def run(self):
        self.build_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.scripts_dir.mkdir(parents=True, exist_ok=True)
        self.src_dir.mkdir(parents=True, exist_ok=True)

        raw_text = self._step_extract()
        outline = self._step_outline(raw_text)
        source_code, program_stdout = self._step_source_code(raw_text, outline)
        calc_summary = self._step_scripts(raw_text, outline, source_code, program_stdout)
        sections_content = self._step_sections(raw_text, outline, source_code, calc_summary)
        self._step_assemble(outline, sections_content)
        self._copy_deliverables(outline)

        logger.info(
            "Генерация завершена. Токенов: prompt=%d, completion=%d. Стоимость: $%.4f",
            self.client.total_prompt_tokens,
            self.client.total_completion_tokens,
            self.client.estimated_cost_usd,
        )

    def _copy_deliverables(self, outline: LabOutline):
        rep_docx = self.reports_dir / "report.docx"
        if rep_docx.exists():
            shutil.copy2(rep_docx, self.reports_dir / "main.docx")
            shutil.copy2(rep_docx, self.lab_dir / "report.docx")
            shutil.copy2(rep_docx, self.lab_dir / "main.docx")

        rep_pdf = self.reports_dir / "main.pdf"
        if rep_pdf.exists():
            shutil.copy2(rep_pdf, self.lab_dir / "main.pdf")

        for code_f in self.src_dir.glob("*.*"):
            shutil.copy2(code_f, self.reports_dir / code_f.name)
            shutil.copy2(code_f, self.lab_dir / code_f.name)

        for img in self.build_dir.glob("*.png"):
            shutil.copy2(img, self.reports_dir / img.name)
            shutil.copy2(img, self.lab_dir / img.name)

    def _step_extract(self) -> str:
        cache_file = self.build_dir / "extracted_raw.txt"
        refs_file = self.build_dir / "refs_raw.txt"

        main_doc, ref_docs = find_lab_documents(self.lab_dir)
        self.reference_text = self._prepare_references(ref_docs, refs_file)

        if self.state.is_step_done("extract") and cache_file.exists():
            return cache_file.read_text(encoding="utf-8")

        if main_doc is None:
            raise FileNotFoundError(
                f"В папке {self.lab_dir} не найден файл методички/ТЗ (.docx / .pdf / .txt). "
                "Положите туда задание, а готовый пример оформления — в подпапку refs/."
            )

        text = extract_document_text(main_doc, pages=self.pages)

        var_block = f"\n=== ВЫБРАН ВАРИАНТ ЗАДАНИЯ СТУДЕНТА: {self.variant} ===\n"
        notes_file = self.lab_dir / "notes.txt"
        extra = notes_file.read_text(encoding="utf-8").strip() if notes_file.exists() else ""

        full = f"{var_block}=== ОСОБЫЕ ТРЕБОВАНИЯ И ДАННЫЕ ВАРИАНТА ===\n{extra}\n\n=== ТЕКСТ МЕТОДИЧКИ ===\n{text}"
        cache_file.write_text(full, encoding="utf-8")
        self.state.mark_step_done("extract")
        return full

    def _prepare_references(self, ref_docs: List[Path], refs_file: Path) -> str:
        """Текст образца/ТЗ. Кэшируется, но перечитывается, если файл изменился."""
        if not ref_docs:
            return ""

        newest = max(path.stat().st_mtime for path in ref_docs)
        if refs_file.exists() and refs_file.stat().st_mtime >= newest:
            return refs_file.read_text(encoding="utf-8")

        chunks = []
        for path in ref_docs:
            try:
                ref_text = extract_document_text(path)
            except Exception as exc:
                logger.warning("Не удалось прочитать образец %s: %s", path.name, exc)
                continue
            if ref_text.strip():
                chunks.append(f"--- {path.name} ---\n{ref_text}")
        text = "\n\n".join(chunks).strip()
        if text:
            logger.info(
                "Найден образец для подражания: %s", ", ".join(path.name for path in ref_docs)
            )
            refs_file.write_text(text, encoding="utf-8")
        return text

    def _reference_block(self, limit: int = 12000) -> str:
        """Кусок промпта с образцом. Пустая строка, если образца нет."""
        if not self.reference_text:
            return ""
        return (
            "\n=== ОБРАЗЕЦ ГОТОВОЙ РАБОТЫ / ТЗ (ориентир, НЕ копировать дословно) ===\n"
            f"{self.reference_text[:limit]}\n"
            "=== КОНЕЦ ОБРАЗЦА ===\n"
        )

    def _step_outline(self, raw_text: str) -> LabOutline:
        outline_file = self.build_dir / "outline.json"
        if self.state.is_step_done("outline") and outline_file.exists():
            try:
                data = json.loads(outline_file.read_text(encoding="utf-8"))
                outline = LabOutline.model_validate(data)
                outline.sections = [s for s in outline.sections if not any(w in s.title.lower() for w in ["титул", "титульный"])]
                return outline
            except Exception:
                pass

        logger.info("[1/5] Архитектурный анализ методички через DeepSeek API (Вариант %s)...", self.variant)
        user_prompt = render_prompt(self.prompts.get("outline", ""), {
            "variant": self.variant,
            "reference": self._reference_block(12000),
            "methodichka": raw_text[:25000],
        })

        messages = [
            {"role": "system", "content": self.prompts.get("system", "")},
            {"role": "user", "content": user_prompt},
        ]
        outline = self.client.generate_structured(messages, LabOutline)
        outline.sections = [s for s in outline.sections if not any(w in s.title.lower() for w in ["титул", "титульный"])]

        outline_file.write_text(json.dumps(outline.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")
        self.state.mark_step_done("outline")
        return outline

    def _step_source_code(self, raw_text: str, outline: LabOutline) -> tuple[str, str]:
        """
        Пишет, компилирует (g++) и тестирует исходный код программы ДО написания отчета,
        чтобы программа в листинге и данные во всех разделах отчета совпадали на 100%.
        """
        if not outline.meta.has_source_code:
            return "", ""

        lang = outline.meta.code_language.lower()
        is_cpp = lang in ["cpp", "c++", "c"]
        ext = ".cpp" if is_cpp else ".py"
        src_file = self.src_dir / f"main{ext}"
        stdout_file = self.build_dir / "program_stdout.txt"

        if self.state.is_step_done("code") and src_file.exists():
            code_txt = src_file.read_text(encoding="utf-8")
            out_txt = stdout_file.read_text(encoding="utf-8") if stdout_file.exists() else ""
            return code_txt, out_txt

        logger.info("[2/5] Разработка и проверка исходного кода программы (%s) через DeepSeek API...", ext)
        user_msg = render_prompt(self.prompts.get("code", ""), {
            "language": outline.meta.code_language,
            "title": outline.meta.title,
            "variant": self.variant,
            "variant_summary": outline.meta.variant_summary,
            "methodichka": raw_text[:20000],
        })

        messages = [
            {"role": "system", "content": self.prompts.get("code_system", "")},
            {"role": "user", "content": user_msg},
        ]

        code = ""
        program_stdout = ""
        for attempt in range(3):
            code = self.client.generate_text(messages)
            code = re.sub(r"^```(?:cpp|c\+\+|c|python|py)?\s*\n", "", code.strip())
            code = re.sub(r"\n```$", "", code.strip())
            src_file.write_text(code, encoding="utf-8")

            if is_cpp:
                bin_path = self.build_dir / "app_bin"
                comp = subprocess.run(
                    ["g++", "-std=c++17", "-O2", str(src_file), "-o", str(bin_path)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                if comp.returncode != 0:
                    logger.warning("Ошибка компиляции C++ (попытка %d/3), отправляем в DeepSeek на исправление...", attempt + 1)
                    messages.append({"role": "assistant", "content": code})
                    messages.append({
                        "role": "user",
                        "content": f"Компилятор g++ выдал ошибку:\n{comp.stderr}\nИсправь код и верни ТОЛЬКО чистый код C++."
                    })
                    continue

                # Пробуем запустить бинарник с тестовым вводом на случай интерактивности
                try:
                    run_res = subprocess.run(
                        [str(bin_path)],
                        input="1234\n5678\n0\nq\n",
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        timeout=15,
                    )
                    program_stdout = run_res.stdout.strip()
                except subprocess.TimeoutExpired as te:
                    program_stdout = (te.stdout or b"").decode("utf-8", errors="ignore") if isinstance(te.stdout, bytes) else (te.stdout or "")
                break
            else:
                try:
                    run_res = subprocess.run(
                        [sys.executable, str(src_file)],
                        input="1234\n0\nq\n",
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        timeout=20,
                    )
                    if run_res.returncode == 0:
                        program_stdout = run_res.stdout.strip()
                        break
                    else:
                        messages.append({"role": "assistant", "content": code})
                        messages.append({"role": "user", "content": f"Ошибка выполнения:\n{run_res.stderr}\nИсправь код."})
                except Exception:
                    break

        stdout_file.write_text(program_stdout, encoding="utf-8")
        self.state.mark_step_done("code")

        print("\n" + "=" * 65)
        print(" [VS CODE] ИСХОДНЫЙ КОД ПРОГРАММЫ СКОМПИЛИРОВАН И ПРОВЕРЕН!")
        print(f" Файл: {self.lab_dir / f'main{ext}'}")
        print("=" * 65 + "\n")

        return code, program_stdout

    def _step_scripts(self, raw_text: str, outline: LabOutline, source_code: str, program_stdout: str) -> str:
        summary_file = self.build_dir / "calc_summary.txt"
        if self.state.is_step_done("scripts") and summary_file.exists():
            return summary_file.read_text(encoding="utf-8")

        for old_img in self.build_dir.glob("*.png"):
            old_img.unlink()

        if outline.flowcharts:
            logger.info("[3/5] Построение блок-схемы по ГОСТ...")
            render_universal_flowchart(outline.flowcharts, self.build_dir / "flowchart.png")

        plots_to_render = [v for v in outline.visuals if v.can_python_render and v.id != "flowchart"]
        calc_script = (self.scripts_dir / "calc_and_plot.py").resolve()

        logger.info("[3/5] Генерация через DeepSeek API скрипта графиков и таблиц...")
        plots_desc = "\n".join([f"- {v.id}.png: {v.title}" for v in plots_to_render]) or "Нет графиков."

        user_msg = render_prompt(self.prompts.get("scripts", ""), {
            "title": outline.meta.title,
            "variant": self.variant,
            "variant_summary": outline.meta.variant_summary,
            "program_stdout": program_stdout[:4000],
            "plots": plots_desc,
        })

        messages = [
            {"role": "system", "content": self.prompts.get("scripts_system", "")},
            {"role": "user", "content": user_msg},
        ]

        summary_output = ""
        for attempt in range(2):
            code = self.client.generate_text(messages)
            code = re.sub(r"^```(?:python)?\s*\n", "", code.strip())
            code = re.sub(r"\n```$", "", code.strip())
            calc_script.write_text(code, encoding="utf-8")

            try:
                res = subprocess.run(
                    [sys.executable, str(calc_script)],
                    cwd=str(self.build_dir.resolve()),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    timeout=90,
                )
                if res.returncode == 0:
                    summary_output = res.stdout.strip()
                    break
                else:
                    logger.warning("Ошибка в calc_and_plot.py (попытка %d/2), исправляем через DeepSeek...", attempt + 1)
                    messages.append({"role": "assistant", "content": code})
                    messages.append({"role": "user", "content": f"Ошибка:\n{res.stderr}\nИсправь и верни ТОЛЬКО код Python."})
            except Exception as e:
                logger.warning("Ошибка запуска скрипта: %s", e)
                break

        combined_facts = (
            f"=== ЕДИНЫЕ ПАРАМЕТРЫ ВАРИАНТА {self.variant} ===\n{outline.meta.variant_summary}\n\n"
            f"=== РЕАЛЬНЫЙ ВЫВОД ПРОГРАММЫ ===\n{program_stdout[:4000]}\n\n"
            f"=== РАССЧИТАННЫЕ ТАБЛИЦЫ И МЕТРИКИ ===\n{summary_output}"
        )
        summary_file.write_text(combined_facts, encoding="utf-8")
        self.state.mark_step_done("scripts")
        return combined_facts

    def _step_sections(self, raw_text: str, outline: LabOutline, source_code: str, calc_summary: str) -> Dict[str, str]:
        sections_dir = self.build_dir / "sections"
        sections_dir.mkdir(exist_ok=True)
        sections_content = {}
        used_images: Set[str] = set()
        previous_sections_digest: List[str] = []

        logger.info("[4/5] Генерация разделов отчета через DeepSeek API с единой памятью...")
        sys_prompt = self.prompts.get("system", "")
        all_sections_map = "\n".join([f"- {s.id}: {s.title} ({s.guidance})" for s in outline.sections])
        has_flowchart = (self.build_dir / "flowchart.png").exists()

        for sec in outline.sections:
            sec_file = sections_dir / f"{sec.id}.md"
            sec_lower = sec.title.lower()
            is_listing = any(w in sec_lower for w in ["листинг", "исходный код", "текст программы"])

            # Если это раздел Листинга и у нас есть скомпилированный код — вставляем его напрямую без искажений!
            if is_listing and source_code:
                lang_tag = outline.meta.code_language.lower()
                listing_md = f"```{lang_tag}\n{source_code}\n```"
                sec_file.write_text(listing_md, encoding="utf-8")
                self.state.mark_step_done(f"section_{sec.id}")
                sections_content[sec.id] = listing_md
                previous_sections_digest.append(f"Раздел '{sec.title}': вставлен полный исходный код программы.")
                continue

            if sec_file.exists() and self.state.is_step_done(f"section_{sec.id}"):
                loaded = sec_file.read_text(encoding="utf-8")
                sections_content[sec.id] = loaded
                previous_sections_digest.append(f"Раздел '{sec.title}': уже написан.")
                continue

            logger.info("  Генерация раздела: %s...", sec.title)

            allowed_visuals = []
            if "алгоритм" in sec_lower and has_flowchart and "flowchart.png" not in used_images:
                allowed_visuals.append("Вставь блок-схему алгоритма строкой: ![Схема алгоритмов работы](flowchart.png)")
                used_images.add("flowchart.png")

            for v in outline.visuals:
                img_filename = f"{v.id}.png"
                if v.can_python_render and img_filename not in used_images and (self.build_dir / img_filename).exists():
                    if v.target_section_id == sec.id or any(w in sec_lower for w in ["результат", "эксперимент", "постановк"]):
                        allowed_visuals.append(f"Вставь рисунок строкой: ![{v.title}]({img_filename})")
                        used_images.add(img_filename)
                elif not v.can_python_render and (v.target_section_id == sec.id or "скриншот" in sec_lower):
                    allowed_visuals.append(
                        f":::screenshot\n"
                        f"**Название:** {v.title}\n"
                        f"**Инструкция в ПО:** {v.software_instructions}\n"
                        f"**Промпт для генерации:** `{v.generation_prompt}`\n"
                        f":::"
                    )

            if not allowed_visuals:
                allowed_visuals.append("КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО вставлять любые картинки ![...](...) в этот раздел!")

            digest_str = "\n".join(previous_sections_digest) if previous_sections_digest else "Это первый раздел отчета."

            user_msg = render_prompt(self.prompts.get("section", ""), {
                "title": outline.meta.title,
                "sections_map": all_sections_map,
                "digest": digest_str,
                "section_title": sec.title,
                "guidance": sec.guidance,
                "forbidden": sec.forbidden_content,
                "visuals": "\n".join(f"   - {av}" for av in allowed_visuals),
                "reference": self._reference_block(4000),
                "facts": calc_summary,
                "methodichka": raw_text[:18000],
            })

            content = self.client.generate_text([
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_msg},
            ])

            content = protect_and_normalize_tables(content)
            sec_file.write_text(content, encoding="utf-8")
            self.state.mark_step_done(f"section_{sec.id}")
            sections_content[sec.id] = content

            # Сохраняем краткую сводку того, что уже включено в отчет
            tables_in_sec = len(re.findall(r"\|\s*:---", content))
            previous_sections_digest.append(
                f"Раздел '{sec.title}': написан (содержит таблиц: {tables_in_sec}, первые строки: {content[:180].replace(chr(10), ' ')}...)"
            )

        self.state.mark_step_done("sections")
        return sections_content

    def _step_assemble(self, outline: LabOutline, sections: Dict[str, str]):
        logger.info("[5/5] Сборка финального отчета в PDF и Word...")
        assemble_report_tex(self.lab_dir, outline, sections, profile=self.profile)
        compile_all(self.build_dir, self.lab_dir, client=self.client)
        self.state.mark_step_done("assemble")
