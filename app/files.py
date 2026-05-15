from pathlib import Path

from app.config import UPLOADS_DIR

TEXT_EXTENSIONS = {".txt", ".md", ".csv", ".json", ".xml", ".html", ".htm"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}


def _read_text_file(path: Path, max_chars: int = 12000) -> str:
    for enc in ("utf-8", "cp1251", "latin-1"):
        try:
            text = path.read_text(encoding=enc)
            return text[:max_chars] + ("…" if len(text) > max_chars else "")
        except UnicodeDecodeError:
            continue
    return "[не удалось прочитать текст файла]"


def _extract_pdf(path: Path, max_chars: int = 12000) -> str:
    try:
        from pypdf import PdfReader  # type: ignore

        reader = PdfReader(str(path))
        parts = []
        for page in reader.pages[:30]:
            parts.append(page.extract_text() or "")
        text = "\n".join(parts)
        return text[:max_chars] + ("…" if len(text) > max_chars else "")
    except Exception as e:
        return f"[PDF: не удалось извлечь текст — {e}]"


async def extract_upload_text(filename: str, content: bytes) -> str:
    ext = Path(filename).suffix.lower()
    session_dir = UPLOADS_DIR
    session_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(filename).name.replace("..", "_")
    path = session_dir / safe_name
    path.write_bytes(content)

    if ext in TEXT_EXTENSIONS:
        return _read_text_file(path)
    if ext == ".pdf":
        return _extract_pdf(path)
    if ext in IMAGE_EXTENSIONS:
        return (
            f"[Изображение: {safe_name}, {len(content)} байт — "
            "опишите визуальный контекст по имени файла; vision-парсинг можно добавить позже]"
        )
    if ext in {".ppt", ".pptx", ".doc", ".docx", ".xls", ".xlsx"}:
        return f"[Документ {safe_name}: загружен, извлечение текста для формата {ext} пока ограничено — опирайтесь на имя и задачу пользователя]"
    return f"[Файл {safe_name}: бинарный/неизвестный формат, {len(content)} байт]"


def build_attachments_context(blocks: list[tuple[str, str]]) -> str:
    if not blocks:
        return ""
    lines = ["## Прикреплённые материалы\n"]
    for name, text in blocks:
        lines.append(f"### {name}\n{text}\n")
    return "\n".join(lines)
