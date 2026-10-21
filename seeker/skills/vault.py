"""Cofre Sexta-feira: um link ou um tema vira nota em E:\\Ideias pelo motor yt2md."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from seeker.skills.contract import Skill

CREATE_NO_WINDOW = 0x08000000
ENGINE = Path(r"E:\Ideias\youtube-to-markdown\yt2md.py")
VAULT = Path(r"E:\Ideias")
TIMEOUT = 900

_URL = re.compile(r"^https?://", re.I)


def vault_skill(vault: Path = VAULT, engine: Path = ENGINE, python: Path | None = None, groq_key: str = "", run=None, probe=None, brain=None, key_of=None) -> Skill:
    runner = run or _run
    look = probe or _probe
    current = key_of or (lambda: groq_key)

    def execute(arguments: dict) -> str:
        query = " ".join(str(arguments.get("query") or "").split())
        scope = "lote" if str(arguments.get("scope") or "") == "lote" else "um"
        if not query:
            return "Diga o link ou o tema para guardar no cofre."
        if not engine.exists():
            return "O motor yt2md não está em E:\\Ideias\\youtube-to-markdown."
        found = find_existing(vault, query)
        if found is not None:
            publish(found, brain)
            return render_folder(found, reused=True)
        info = look(query) if _URL.match(query) and scope == "um" else None
        dest = destination(vault, query, info, scope)
        if (dest / "INDEX.md").exists():
            return render_folder(dest, reused=True)
        dest.mkdir(parents=True, exist_ok=True)
        raw = runner(command(engine, python or Path(sys.executable), query, dest, scope), current())
        try:
            payload = parse_result(raw)
        except ValueError as exc:
            return str(exc)
        folder = Path(str(payload.get("output_dir") or payload.get("parent_dir") or dest))
        publish(folder, brain, payload)
        return render_folder(folder, reused=False, payload=payload)

    return Skill(
        name="knowledge_vault",
        when=(
            "Guarda um vídeo ou um tema no cofre E:\\Ideias pelo protocolo Sexta-feira. "
            "Use quando a pessoa mandar um link ou pedir para extrair um assunto."
        ),
        risk="altera",
        needs_approval=True,
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "URL do vídeo ou palavras do tema."},
                "scope": {"type": "string", "description": "um para um vídeo. lote para três vídeos do tema."},
            },
            "required": ["query"],
        },
        run=execute,
    )


def command(engine: Path, python: Path, query: str, dest: Path, scope: str) -> list[str]:
    argv = [str(python), str(engine), query, "--json", "--lang", "en,pt", "-o", str(dest)]
    if _URL.match(query):
        if scope == "lote":
            argv.append("--playlist")
        else:
            argv.append("--single-video")
    elif scope == "lote":
        argv.extend(["-s", "3", "--all"])
    else:
        argv.extend(["--pick", "1"])
    return argv


def destination(vault: Path, query: str, info: dict | None, scope: str) -> Path:
    if _URL.match(query) and scope == "um":
        title = (info or {}).get("title") or video_id(query) or "Video"
        author = (info or {}).get("author") or "Autor"
        return vault / slug(f"{title} - {author}")
    return vault / slug("Pesquisa " + query)


def find_existing(vault: Path, query: str) -> Path | None:
    token = video_id(query) or ""
    if not token or not vault.exists():
        return None
    seen = 0
    for path in vault.glob("*/video_info.json"):
        seen += 1
        if seen > 500:
            break
        if _json_has(path, token):
            return path.parent
    for path in vault.glob("*/*/video_info.json"):
        seen += 1
        if seen > 800:
            break
        if _json_has(path, token):
            return path.parent
    return None


def publish(folder: Path, brain=None, payload: dict | None = None) -> Path | None:
    """Grava a ficha curta no material e, se houver cérebro, uma cópia buscável."""
    meta = _read_json(folder / "video_info.json")
    if payload:
        meta = {**meta, "title": payload.get("title") or meta.get("title"), "author": payload.get("author") or meta.get("author")}
    title = str(meta.get("title") or folder.name)
    author = str(meta.get("author") or "")
    url = str(meta.get("url") or "")
    thesis = _thesis(folder)
    action = _action(folder)
    tags = card_tags(meta, "video" if url else "pesquisa")
    ficha = folder / "FICHA.md"
    if not ficha.exists():
        ficha.write_text(card_text(title, author, url, tags, thesis, action, folder, local=True), encoding="utf-8")
    if brain is None:
        return None
    name = slug(title)
    note = brain.write_cofre(name, card_text(title, author, url, tags, thesis, action, folder, local=False))
    _relate(brain.root / "cofre", name, tags)
    return note


def card_tags(meta: dict, kind: str) -> list[str]:
    found = [kind]
    for item in meta.get("tags") or []:
        tag = re.sub(r"[^\w\-]+", "-", str(item).casefold()).strip("-")
        if len(tag) < 3 or tag in found or tag in {"para", "como", "isso", "sobre", "video", "pesquisa"}:
            continue
        found.append(tag)
        if len(found) == 6:
            break
    return found


def card_text(title: str, author: str, url: str, tags: list[str], thesis: str, action: str, folder: Path, local: bool) -> str:
    tag_lines = "\n".join(f"  - {tag}" for tag in tags)
    lines = [
        "---",
        "tipo: cofre",
        f"titulo: {_yaml(title)}",
        f"autor: {_yaml(author)}",
        f"url: {_yaml(url)}",
        "tags:",
        tag_lines,
        "---",
        "",
        f"# {title}",
        "",
        thesis or "O material não trouxe um trecho curto para a tese.",
        "",
        f"Próxima ação: {action}",
        "",
    ]
    index = folder / "INDEX.md"
    if local and index.exists():
        lines.append(f"Material: [[{folder.name}/INDEX|Índice]]")
        if (folder / "transcript.md").exists():
            lines.append(f"Transcrição: [[{folder.name}/transcript|Transcrição]]")
        if (folder / "STRATEGIES.md").exists():
            lines.append(f"SOP: [[{folder.name}/STRATEGIES|SOP]]")
    elif index.exists():
        lines.append(f"Material: [Índice]({file_uri(index)})")
    return "\n".join(lines).rstrip() + "\n"


def render_folder(folder: Path, reused: bool, payload: dict | None = None) -> str:
    meta = _read_json(folder / "video_info.json")
    title = str((payload or {}).get("title") or meta.get("title") or folder.name)
    author = str((payload or {}).get("author") or (payload or {}).get("playlist_title") or meta.get("author") or "")
    duration = _clock(meta.get("duration"))
    lines = [title]
    if author or duration:
        lines.append(" · ".join(part for part in (author, duration) if part))
    if reused:
        lines.append("Esta nota já estava no cofre. Não baixei de novo.")
    else:
        lines.append(f"Nota nova em {folder}")
    lines.append("")
    lines.append("Arquivos:")
    for label, path in _links(folder, payload).items():
        lines.append(f"- {label}: {file_uri(path)}")
    excerpt = _excerpt(folder / "STRATEGIES.md") or _excerpt(folder / "transcript.md")
    if excerpt:
        lines.extend(["", "Trecho para os insights, sem completar de cabeça:", excerpt])
    else:
        lines.append("")
        lines.append("O motor não deixou SOP nem transcrição para citar.")
    if (folder / "FICHA.md").exists():
        lines.append(f"Ficha: {file_uri(folder / 'FICHA.md')}")
    return "\n".join(lines)


def parse_result(text: str) -> dict:
    raw = (text or "").strip()
    if not raw:
        raise ValueError("O yt2md não devolveu resultado.")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.rfind("\n{")
        if start < 0:
            raise ValueError("O yt2md não devolveu JSON.")
        data = json.loads(raw[start + 1:])
    if not isinstance(data, dict):
        raise ValueError("O yt2md devolveu um JSON inesperado.")
    if data.get("status") == "error":
        raise ValueError(str(data.get("message") or "O yt2md falhou."))
    return data


def slug(text: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]', " ", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().rstrip(".")
    return cleaned[:80] or "Ideia"


def video_id(url: str) -> str:
    if not _URL.match(url):
        return ""
    parsed = urlparse(url)
    found = parse_qs(parsed.query).get("v", [""])[0]
    if found:
        return found
    if "youtu.be" in parsed.netloc.lower():
        return parsed.path.strip("/").split("/")[0]
    return ""


def file_uri(path: Path) -> str:
    return "file:///" + path.resolve().as_posix()


def _run(argv: list[str], groq_key: str) -> str:
    env = os.environ.copy()
    env["YT2MD_NON_INTERACTIVE"] = "1"
    if groq_key:
        env["GROQ_API_KEY"] = groq_key
    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
            encoding="utf-8",
            errors="replace",
            env=env,
            creationflags=CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        return json.dumps({"status": "error", "message": "A extração passou de 15 minutos."})
    except OSError as exc:
        return json.dumps({"status": "error", "message": str(exc)})
    if completed.returncode != 0 and not completed.stdout.strip():
        return json.dumps({"status": "error", "message": (completed.stderr or "O yt2md falhou.")[-1500:]})
    return completed.stdout


def _probe(query: str) -> dict | None:
    if not _URL.match(query):
        return None
    try:
        completed = subprocess.run(
            ["yt-dlp", "--skip-download", "--no-warnings", "--print", "%(title)s\t%(uploader)s", query],
            capture_output=True,
            text=True,
            timeout=40,
            encoding="utf-8",
            errors="replace",
            creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    line = (completed.stdout or "").strip().splitlines()
    if not line or "\t" not in line[-1]:
        return None
    title, author = line[-1].split("\t", 1)
    return {"title": title.strip(), "author": author.strip()}


def _json_has(path: Path, token: str) -> bool:
    try:
        text = path.read_text(encoding="utf-8")[:20000]
    except OSError:
        return False
    return token in text


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _links(folder: Path, payload: dict | None) -> dict[str, Path]:
    inventory = (payload or {}).get("inventory") if isinstance((payload or {}).get("inventory"), dict) else {}
    found: dict[str, Path] = {}
    for label, value in inventory.items():
        path = Path(str(value))
        if path.exists():
            found[str(label)] = path
    if found:
        return found
    names = {
        "INDEX.md": "Índice",
        "transcript.md": "Transcrição",
        "video_report.md": "Decupagem",
        "STRATEGIES.md": "SOP",
        "MINDMAP.md": "Mapa",
        "mindmap.canvas": "Canvas",
        "comments.md": "Comentários",
        "PLAYLIST_SUMMARY.md": "Resumo do lote",
        "SEARCH_SUMMARY.md": "Resumo da busca",
    }
    for name, label in names.items():
        path = folder / name
        if path.exists():
            found[label] = path
    return found


def _thesis(folder: Path) -> str:
    for name in ("STRATEGIES.md", "transcript.md"):
        text = _plain(folder / name)
        if text:
            return text[:500]
    return ""


def _action(folder: Path) -> str:
    path = folder / "STRATEGIES.md"
    if not path.exists():
        return "Abrir o índice e escolher um passo."
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return "Abrir o índice e escolher um passo."
    for line in lines:
        stripped = line.strip()
        if re.match(r"^(\d+\.|-)\s+\S", stripped) and not stripped.startswith("---"):
            return _clip_line(re.sub(r"^(\d+\.|-)\s+", "", stripped))
    return "Abrir o índice e escolher um passo."


def _plain(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    chunks = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("|") or stripped.startswith("---"):
            continue
        chunks.append(stripped[:180])
        if len(" ".join(chunks)) > 400:
            break
    return " ".join(chunks)[:500]


def _relate(folder: Path, name: str, tags: list[str]) -> None:
    meaningful = [tag for tag in tags if tag not in {"video", "pesquisa"}]
    if not meaningful:
        return
    own = folder / f"{name}.md"
    for path in folder.glob("*.md"):
        if path.stem == name:
            continue
        try:
            body = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if not any(f"- {tag}" in body for tag in meaningful):
            continue
        _add_link(own, path.stem)
        _add_link(path, name)


def _add_link(path: Path, stem: str) -> None:
    if not path.exists():
        return
    link = f"[[{stem}]]"
    text = path.read_text(encoding="utf-8")
    if link in text:
        return
    if "## Relacionados" not in text:
        text = text.rstrip() + "\n\n## Relacionados\n"
    path.write_text(text.rstrip() + f"\n- {link}\n", encoding="utf-8")


def _yaml(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _clip_line(text: str) -> str:
    clean = " ".join(text.split())
    if len(clean) <= 180:
        return clean
    return clean[:180] + "…"


def _excerpt(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    return text[:1800]


def _clock(value) -> str:
    try:
        seconds = int(float(value))
    except (TypeError, ValueError):
        return ""
    if seconds <= 0:
        return ""
    minutes, rest = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h{minutes:02d}"
    return f"{minutes}min{rest:02d}s"
