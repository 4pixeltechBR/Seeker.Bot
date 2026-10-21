"""Pesquisa que só vale como fato quando volta com fonte."""

from __future__ import annotations

from dataclasses import dataclass

from seeker.skills.contract import Skill

NO_SOURCE = "A pesquisa não trouxe fonte. Não trate o texto como fato."


@dataclass(frozen=True)
class Source:
    title: str
    url: str


@dataclass(frozen=True)
class Evidence:
    text: str
    sources: tuple[Source, ...]


def evidence_from_payload(payload: dict) -> Evidence:
    texts: list[str] = []
    sources: list[Source] = []
    seen: set[str] = set()
    for candidate in payload.get("candidates") or []:
        for part in (candidate.get("content") or {}).get("parts") or []:
            if part.get("text") and not part.get("thought"):
                texts.append(part["text"])
        metadata = candidate.get("groundingMetadata") or candidate.get("grounding_metadata") or {}
        chunks = metadata.get("groundingChunks") or metadata.get("grounding_chunks") or []
        for chunk in chunks:
            web = chunk.get("web") or {}
            url = str(web.get("uri") or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            title = str(web.get("title") or url).strip()
            sources.append(Source(title, url))
    return Evidence("\n".join(texts).strip(), tuple(sources))


def format_research(evidence: Evidence) -> str:
    if not evidence.sources:
        return NO_SOURCE
    body = evidence.text.strip() or "Sem resumo."
    lines = [body, "", "Fontes:"]
    for index, source in enumerate(evidence.sources[:5], start=1):
        lines.append(f"{index}. {source.title} — {source.url}")
    return "\n".join(lines)


def research_skill(lookup) -> Skill:
    def run(arguments: dict) -> str:
        query = " ".join(str(arguments.get("query") or "").split())
        if not query:
            return "Diga o que pesquisar."
        found = lookup(query)
        if isinstance(found, Evidence):
            return format_research(found)
        if isinstance(found, str) and found.strip():
            return found.strip()
        return NO_SOURCE

    return Skill(
        name="research",
        when=(
            "Pesquisa um fato na web e devolve o texto com as fontes numeradas. "
            "Use para notícia, dado atual ou qualquer afirmação que precise de origem."
        ),
        risk="leitura",
        needs_approval=False,
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string", "description": "O que pesquisar."}},
            "required": ["query"],
        },
        run=run,
    )
