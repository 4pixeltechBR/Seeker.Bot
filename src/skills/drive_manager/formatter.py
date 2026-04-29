"""
Seeker.Bot — Drive Formatter
src/skills/drive_manager/formatter.py

Formata listas de arquivos do Drive para HTML do Telegram.
"""

MIME_ICONS = {
    "application/vnd.google-apps.folder": "📁",
    "application/vnd.google-apps.document": "📝",
    "application/vnd.google-apps.spreadsheet": "📊",
    "application/vnd.google-apps.presentation": "📊",
    "application/vnd.google-apps.form": "📋",
    "application/pdf": "📄",
    "image/jpeg": "🖼️",
    "image/png": "🖼️",
    "image/gif": "🖼️",
    "video/mp4": "🎬",
    "audio/mpeg": "🎵",
    "audio/mp4": "🎵",
    "text/plain": "📃",
    "application/zip": "🗜️",
    "application/x-zip-compressed": "🗜️",
}
_DEFAULT_ICON = "📎"


def _icon(mime: str) -> str:
    return MIME_ICONS.get(mime, _DEFAULT_ICON)


def _size_str(size_bytes: str | None) -> str:
    if not size_bytes:
        return ""
    try:
        b = int(size_bytes)
        if b < 1024:
            return f"{b}B"
        if b < 1024 ** 2:
            return f"{b/1024:.1f}KB"
        if b < 1024 ** 3:
            return f"{b/1024**2:.1f}MB"
        return f"{b/1024**3:.1f}GB"
    except (ValueError, TypeError):
        return ""


def format_file_list(files: list[dict], folder_name: str = "root") -> str:
    """Formata lista de arquivos para HTML do Telegram."""
    if not files:
        return f"📂 <b>{folder_name}</b>\n\n<i>Pasta vazia.</i>"

    lines = [f"📂 <b>{folder_name}</b> — {len(files)} item(s)\n"]

    for f in files:
        icon = _icon(f.get("mimeType", ""))
        name = f.get("name", "?")
        fid = f.get("id", "")
        size = _size_str(f.get("size"))
        size_part = f" <i>({size})</i>" if size else ""
        # Formato: ícone nome [tamanho] • id curto
        short_id = fid[:12] + "…" if len(fid) > 12 else fid
        lines.append(f"{icon} <code>{name}</code>{size_part}\n   <i>ID: <code>{fid}</code></i>")

    return "\n\n".join(lines)


def format_file_info(item: dict) -> str:
    """Formata detalhes de um único arquivo/pasta."""
    icon = _icon(item.get("mimeType", ""))
    name = item.get("name", "?")
    fid = item.get("id", "")
    mime = item.get("mimeType", "?")
    size = _size_str(item.get("size"))
    modified = item.get("modifiedTime", "?")[:10]  # só a data
    created = item.get("createdTime", "?")[:10]
    link = item.get("webViewLink", "")

    lines = [
        f"{icon} <b>{name}</b>",
        f"📌 <b>ID:</b> <code>{fid}</code>",
        f"📦 <b>Tipo:</b> <code>{mime}</code>",
    ]
    if size:
        lines.append(f"💾 <b>Tamanho:</b> {size}")
    lines.append(f"🗓 <b>Criado:</b> {created}")
    lines.append(f"✏️ <b>Modificado:</b> {modified}")
    if link:
        lines.append(f'🔗 <a href="{link}">Abrir no Drive</a>')

    return "\n".join(lines)


def format_search_results(files: list[dict], query: str) -> str:
    """Formata resultados de busca."""
    if not files:
        return f"🔍 Nenhum resultado para <b>{query}</b>."

    lines = [f'🔍 <b>Resultados para "{query}"</b> — {len(files)} encontrado(s)\n']
    for f in files:
        icon = _icon(f.get("mimeType", ""))
        name = f.get("name", "?")
        fid = f.get("id", "")
        size = _size_str(f.get("size"))
        size_part = f" <i>({size})</i>" if size else ""
        lines.append(f"{icon} <code>{name}</code>{size_part}\n   <code>{fid}</code>")

    return "\n\n".join(lines)
