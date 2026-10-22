import re
import zipfile
from pathlib import Path
from typing import List, Optional, Set, Tuple
import docx2txt
from pypdf import PdfReader

DOC_EXTENSIONS = {".docx", ".pdf", ".txt", ".md"}
# Файлы результатов самого пайплайна — их нельзя принимать за методичку
ARTIFACT_NAMES = {"report.docx", "main.docx", "main.pdf", "report.pdf", "notes.txt"}
# Подпапки, всё содержимое которых считается образцом/ТЗ
REFERENCE_DIRS = {
    "refs", "ref", "reference", "references", "example", "examples",
    "образец", "образцы", "пример", "примеры", "эталон",
}
# Файлы с такими именами в корне работы — тоже образец
_REFERENCE_NAME_RE = re.compile(
    r"^(example|sample|reference|ref|образец|образцы|пример|примеры|эталон|готов)",
    re.IGNORECASE,
)
# Чем раньше ключ в списке, тем выше приоритет файла как задания
TASK_HINTS = ("тз", "техническое задание", "задание", "зачет", "зачёт", "методичк", "лаборатор", "lab")


def parse_pages_spec(pages_str: str, total_pages: int) -> Set[int]:
    selected = set()
    for part in pages_str.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_s, end_s = part.split("-", 1)
            start = max(1, int(start_s.strip()))
            end = min(total_pages, int(end_s.strip()))
            for p in range(start, end + 1):
                selected.add(p - 1)
        else:
            p = int(part)
            if 1 <= p <= total_pages:
                selected.add(p - 1)
    return selected


def _extract_docx_with_tables(path: Path) -> str:
    """Извлекает текст и таблицы из .docx в точном порядке следования в формате Markdown."""
    try:
        from docx import Document
        from docx.table import Table
        from docx.text.paragraph import Paragraph
    except ImportError:
        return (docx2txt.process(str(path)) or "").strip()

    doc = Document(str(path))
    blocks = []

    for child in doc.element.body.iterchildren():
        if child.tag.endswith("p"):
            para = Paragraph(child, doc)
            txt = para.text.strip()
            if txt:
                blocks.append(txt)
        elif child.tag.endswith("tbl"):
            table = Table(child, doc)
            rows_md = []
            for r_idx, row in enumerate(table.rows):
                cells = [c.text.strip().replace("\n", " ") for c in row.cells]
                rows_md.append("| " + " | ".join(cells) + " |")
                if r_idx == 0:
                    rows_md.append("| " + " | ".join(["---"] * len(cells)) + " |")
            if rows_md:
                blocks.append("\n" + "\n".join(rows_md) + "\n")

    # Проверяем наличие встроенных картинок в архиве .docx
    media_count = 0
    try:
        with zipfile.ZipFile(path, "r") as zf:
            media_files = [f for f in zf.namelist() if f.startswith("word/media/")]
            media_count = len(media_files)
    except Exception:
        pass

    if media_count > 0:
        blocks.append(
            f"\n[СИСТЕМНОЕ ПРИМЕЧАНИЕ: В документе методички содержится {media_count} встроенных изображений. "
            "Если параметры варианта заданы на картинке, используй данные из блока ОСОБЫЕ ТРЕБОВАНИЯ (notes.txt).]"
        )

    return "\n\n".join(blocks).strip()


def extract_document_text(file_path: Path, pages: Optional[str] = None) -> str:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Файл не найден: {path}")

    ext = path.suffix.lower()

    if ext in [".txt", ".md"]:
        try:
            return path.read_text(encoding="utf-8").strip()
        except UnicodeDecodeError:
            return path.read_text(encoding="cp1251", errors="ignore").strip()

    elif ext == ".pdf":
        reader = PdfReader(str(path))
        total = len(reader.pages)
        indices = sorted(list(parse_pages_spec(pages, total))) if pages else list(range(total))
        pages_text = []
        for idx in indices:
            text = reader.pages[idx].extract_text() or ""
            if text.strip():
                pages_text.append(text.strip())
        return "\n\n".join(pages_text)

    elif ext == ".docx":
        return _extract_docx_with_tables(path)

    else:
        raise ValueError(f"Неподдерживаемый формат файла: {ext}")


def _looks_like_reference(path: Path) -> bool:
    return bool(_REFERENCE_NAME_RE.match(path.stem.strip()))


def _task_priority(path: Path) -> int:
    name = path.name.lower()
    for idx, hint in enumerate(TASK_HINTS):
        if hint in name:
            return idx
    return len(TASK_HINTS)


def find_lab_documents(lab_dir: Path) -> Tuple[Optional[Path], List[Path]]:
    """Находит в папке работы (задание, образцы).

    Образцами считаются:
      * любые документы из подпапок refs/, example/, образец/ и т.п.;
      * файлы в корне с именем example*, sample*, образец*, пример*, готов* и т.п.

    Из остальных документов выбирается задание: приоритет у «ТЗ», «задание»,
    «методичка», «лабораторная». Возвращает (задание, [образцы]).
    """
    lab_dir = Path(lab_dir)
    if not lab_dir.is_dir():
        return None, []

    references: List[Path] = []
    candidates: List[Path] = []

    for entry in sorted(lab_dir.iterdir()):
        if entry.is_dir():
            if entry.name.lower() not in REFERENCE_DIRS:
                continue
            for path in sorted(entry.rglob("*")):
                if (
                    path.is_file()
                    and path.suffix.lower() in DOC_EXTENSIONS
                    and not path.name.startswith("~$")
                ):
                    references.append(path)
            continue

        if not entry.is_file():
            continue
        if entry.name.startswith("~$"):
            continue
        if entry.suffix.lower() not in DOC_EXTENSIONS:
            continue
        if entry.name.lower() in ARTIFACT_NAMES:
            continue

        if _looks_like_reference(entry):
            references.append(entry)
        else:
            candidates.append(entry)

    candidates.sort(key=lambda p: (_task_priority(p), p.name.lower()))
    main: Optional[Path] = candidates[0] if candidates else None

    # В папке только образец — используем его как задание, чтобы не падать зря.
    if main is None and references:
        main = references.pop(0)

    return main, references
