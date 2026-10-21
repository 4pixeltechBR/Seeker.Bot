"""Cérebro em Markdown. O Obsidian abre a pasta; o Seeker busca por palavras."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from pathlib import Path

from seeker.schedule import TZ

STOP = {
    "para", "como", "isso", "essa", "esse", "aquele", "aquela", "sobre", "quando",
    "onde", "porque", "pelo", "pela", "mais", "menos", "muito", "também", "tambem",
    "você", "voce", "seeker", "hoje", "ontem", "amanha", "amanhã",
}


class Brain:
    def __init__(self, root: Path):
        self.root = root
        for folder in ("diario", "licoes", "memorias", "cofre"):
            (root / folder).mkdir(parents=True, exist_ok=True)
        readme = root / "Leia-me.md"
        bullet = "- `cofre` guarda uma ficha curta de cada material, com tags e links.\n"
        if not readme.exists():
            readme.write_text(
                "# Cérebro do Seeker\n\n"
                "Abra esta pasta no Obsidian.\n\n"
                "- `diario` guarda o que foi falado.\n"
                "- `licoes` guarda o que ele aprendeu no fim do dia.\n"
                "- `memorias` guarda preferências estáveis.\n"
                + bullet,
                encoding="utf-8",
            )
        elif "`cofre`" not in readme.read_text(encoding="utf-8"):
            readme.write_text(readme.read_text(encoding="utf-8").rstrip() + "\n" + bullet, encoding="utf-8")

    def log_exchange(self, when: datetime, user_text: str, answer: str) -> None:
        when = when.astimezone(TZ)
        path = self.root / "diario" / f"{when.date().isoformat()}.md"
        block = f"\n- {when.strftime('%H:%M')} Pessoa: {_clip(user_text, 400)}\n  Seeker: {_clip(answer, 400)}\n"
        _append(path, f"# {when.date().isoformat()}\n", block)

    def write_lesson(self, when: datetime, lesson: str) -> None:
        when = when.astimezone(TZ)
        path = self.root / "licoes" / f"{when.date().isoformat()}.md"
        _append(path, f"# Lições de {when.date().isoformat()}\n", f"\n- {lesson.strip()}\n")

    def write_memory(self, text: str) -> None:
        clean = " ".join(text.split())
        digest = hashlib.sha256(clean.encode("utf-8")).hexdigest()[:10]
        path = self.root / "memorias" / f"{digest}.md"
        path.write_text(f"---\ntipo: memoria\n---\n\n{clean}\n", encoding="utf-8")

    def forget(self, query: str) -> int:
        text = (query or "").strip().casefold()
        if not text:
            return 0
        gone = 0
        for path in (self.root / "memorias").glob("*.md"):
            if text in path.read_text(encoding="utf-8").casefold():
                path.unlink()
                gone += 1
        for path in (self.root / "licoes").glob("*.md"):
            lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
            kept = [line for line in lines if text not in line.casefold()]
            if len(kept) != len(lines):
                path.write_text("".join(kept), encoding="utf-8")
                gone += 1
        return gone

    def write_cofre(self, name: str, text: str) -> Path:
        path = self.root / "cofre" / f"{name}.md"
        if not path.exists():
            path.write_text(text, encoding="utf-8")
        return path

    def search(self, query: str, limit: int = 4) -> list[str]:
        tokens = _tokens(query)
        if not tokens:
            return []
        ranked: list[tuple[int, str]] = []
        for path in self.root.rglob("*.md"):
            if path.name == "Leia-me.md":
                continue
            body = path.read_text(encoding="utf-8")
            hay = body.casefold()
            hits = sum(1 for token in tokens if token in hay)
            if hits == 0:
                continue
            weight = {"cofre": 3, "memorias": 3, "licoes": 2, "diario": 1}.get(path.parent.name, 1)
            snippet = _snippet(body, tokens)
            ranked.append((hits * weight, f"{path.parent.name}/{path.stem}: {snippet}"))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return [line for _score, line in ranked[:limit]]


def _append(path: Path, title: str, block: str) -> None:
    current = path.read_text(encoding="utf-8") if path.exists() else title
    if block.strip() in current:
        return
    path.write_text(current.rstrip() + block, encoding="utf-8")


def _clip(text: str, limit: int) -> str:
    clean = " ".join(text.split())
    if len(clean) <= limit:
        return clean
    return clean[:limit] + "…"


def _tokens(query: str) -> list[str]:
    words = re.findall(r"[0-9A-Za-zÀ-ÿ]{4,}", query.casefold())
    return [word for word in words if word not in STOP]


def _snippet(body: str, tokens: list[str]) -> str:
    for line in body.splitlines():
        folded = line.casefold()
        if any(token in folded for token in tokens) and not line.startswith("#") and not line.startswith("---"):
            return _clip(line.lstrip("- ").strip(), 220)
    return _clip(body, 220)
