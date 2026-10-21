"""O que as pessoas engajaram nos últimos 30 dias, com fonte. Sem cookie e sem chave."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlparse

from seeker.skills.contract import Skill
from seeker.skills.research import NO_SOURCE

WINDOW_DAYS = 30
PER_SOURCE = 3
HOSTS = {"hn.algolia.com", "www.reddit.com", "api.github.com", "gamma-api.polymarket.com"}


def last30_skill(fetch) -> Skill:
    def run(arguments: dict) -> str:
        query = " ".join(str(arguments.get("query") or "").split())
        if not query:
            return "Diga o tema dos últimos 30 dias."
        hits, notes = gather(fetch, query, datetime.now(timezone.utc))
        return format_brief(query, hits, notes)

    return Skill(
        name="last30days",
        when=(
            "Pesquisa o que as pessoas engajaram nos últimos 30 dias em Hacker News, Reddit, "
            "GitHub e Polymarket. Use para tendência, pessoa ou comparação recente. Devolve fonte."
        ),
        risk="leitura",
        needs_approval=False,
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Tema, pessoa ou comparação."}},
            "required": ["query"],
        },
        run=run,
    )


def gather(fetch, query: str, now: datetime, days: int = WINDOW_DAYS) -> tuple[list[dict], list[str]]:
    since = now - timedelta(days=max(1, days))
    stamp = int(since.timestamp())
    day = since.date().isoformat()
    encoded = quote(query)
    reddit_window = "day" if days <= 1 else "month"
    jobs = [
        ("Hacker News", f"https://hn.algolia.com/api/v1/search?query={encoded}&tags=story&hitsPerPage=8&numericFilters=created_at_i%3E{stamp}", parse_hn),
        ("Reddit", f"https://www.reddit.com/search.rss?q={encoded}&sort=new&t={reddit_window}", parse_reddit),
        ("GitHub", f"https://api.github.com/search/repositories?q={encoded}+pushed:%3E{day}&sort=stars&order=desc&per_page=5", parse_github),
        ("Polymarket", f"https://gamma-api.polymarket.com/public-search?q={encoded}&limit_per_type=5", parse_polymarket),
    ]
    hits: list[dict] = []
    notes: list[str] = []
    for name, url, parser in jobs:
        status, body = _safe_fetch(fetch, url)
        if status != 200 or not body.strip():
            notes.append(f"{name} não abriu.")
            continue
        found = parser(body)[:PER_SOURCE]
        if not found:
            notes.append(f"{name} não trouxe item no prazo.")
            continue
        hits.extend(found)
    hits.sort(key=lambda item: item["score"], reverse=True)
    return hits, notes


def format_brief(query: str, hits: list[dict], notes: list[str]) -> str:
    if not hits:
        return NO_SOURCE
    lines = [f"Últimos 30 dias: {query}", ""]
    for index, item in enumerate(hits, start=1):
        score = f" — {item['score']} {item['unit']}" if item["score"] else ""
        lines.append(f"{index}. [{item['source']}] {item['title']}{score}")
        lines.append(f"   {item['url']}")
    if notes:
        lines.extend(["", "Sem resultado: " + " ".join(notes)])
    lines.extend(["", "Fontes:"])
    for index, item in enumerate(hits, start=1):
        lines.append(f"{index}. {item['title']} — {item['url']}")
    return "\n".join(lines)


def parse_hn(body: str) -> list[dict]:
    data = _json(body)
    found = []
    for hit in data.get("hits") or []:
        title = str(hit.get("title") or "").strip()
        if not title:
            continue
        url = str(hit.get("url") or "").strip()
        if not url:
            url = f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
        found.append(_hit("Hacker News", title, url, int(hit.get("points") or 0), "pontos"))
    return found


def parse_reddit(body: str) -> list[dict]:
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return []
    found = []
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1] != "item":
            continue
        title = ""
        link = ""
        for child in list(node):
            name = child.tag.rsplit("}", 1)[-1]
            if name == "title" and child.text:
                title = " ".join(child.text.split())
            if name == "link" and child.text:
                link = child.text.strip()
        if title and link:
            found.append(_hit("Reddit", title, link, 0, ""))
    return found


def parse_github(body: str) -> list[dict]:
    data = _json(body)
    found = []
    for repo in data.get("items") or []:
        title = str(repo.get("full_name") or "").strip()
        url = str(repo.get("html_url") or "").strip()
        if not title or not url:
            continue
        found.append(_hit("GitHub", title, url, int(repo.get("stargazers_count") or 0), "estrelas"))
    return found


def parse_polymarket(body: str) -> list[dict]:
    data = _json(body)
    found = []
    for event in data.get("events") or []:
        title = str(event.get("title") or "").strip()
        slug = str(event.get("slug") or "").strip()
        if not title or not slug:
            continue
        volume = int(float(event.get("volume") or 0))
        found.append(_hit("Polymarket", title, f"https://polymarket.com/event/{slug}", volume, "volume"))
    return found


def _hit(source: str, title: str, url: str, score: int, unit: str) -> dict:
    return {"source": source, "title": title, "url": url, "score": score, "unit": unit}


def _json(body: str) -> dict:
    try:
        data = json.loads(body or "")
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _safe_fetch(fetch, url: str) -> tuple[int, str]:
    parsed = urlparse(url)
    if parsed.scheme != "https" or (parsed.hostname or "") not in HOSTS:
        return 0, ""
    try:
        status, body = fetch(url)
        return int(status), str(body or "")
    except (TypeError, ValueError):
        return 0, ""
