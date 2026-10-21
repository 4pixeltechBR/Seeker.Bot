"""Lê um feed RSS ou Atom e devolve os itens recentes, com data e link."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from html.parser import HTMLParser

from seeker.browser import BrowserError, PageReader, check_url
from seeker.skills.contract import Skill

CAP = 12


class _Plain(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data):
        text = " ".join(data.split())
        if text:
            self.parts.append(text)


def plain(value: str) -> str:
    parser = _Plain()
    parser.feed(value or "")
    return " ".join(parser.parts).strip()


def parse_feed(xml: str, limit: int = 8) -> tuple[str, list[dict]]:
    try:
        root = ET.fromstring(xml or "")
    except ET.ParseError as exc:
        raise BrowserError("O feed não é XML.") from exc
    title = _text(root.find("channel/title")) or _text(_child(root, "title")) or "Feed"
    items = []
    for node in root.iter():
        kind = _local(node.tag)
        if kind not in {"item", "entry"}:
            continue
        name = _text(_child(node, "title"))
        link = _link(node)
        when = _text(_child(node, "pubDate")) or _text(_child(node, "updated")) or _text(_child(node, "published"))
        summary = plain(_text(_child(node, "description")) or _text(_child(node, "summary")) or _text(_child(node, "content")))
        if not name and not link:
            continue
        items.append({"title": name or link, "link": link, "when": when, "summary": summary[:280]})
        if len(items) >= max(1, min(limit, CAP)):
            break
    return title, items


def format_feed(title: str, items: list[dict], source: str) -> str:
    if not items:
        return f"{title} não tinha itens.\n\nFonte: {source}"
    lines = [title, ""]
    for index, item in enumerate(items, start=1):
        when = f" — {item['when']}" if item["when"] else ""
        lines.append(f"{index}. {item['title']}{when}")
        if item["summary"]:
            lines.append(f"   {item['summary']}")
        if item["link"]:
            lines.append(f"   {item['link']}")
    lines.extend(["", f"Fonte: {source}"])
    return "\n".join(lines)


def read_feed_skill(reader: PageReader) -> Skill:
    def run(arguments: dict) -> str:
        url = str(arguments.get("url") or "")
        try:
            limit = int(arguments.get("limit") or 8)
        except (TypeError, ValueError):
            limit = 8
        try:
            safe = check_url(url, reader.resolve)
            response = reader.client.request("GET", safe, follow_redirects=True, timeout=20.0)
            check_url(str(response.url), reader.resolve)
        except BrowserError as exc:
            return str(exc)
        except Exception:
            return "O feed não abriu."
        if response.status_code >= 400:
            return f"O feed não abriu (HTTP {response.status_code}).\n\nFonte: {safe}"
        try:
            title, items = parse_feed(response.text, limit)
        except BrowserError as exc:
            return str(exc)
        return format_feed(title, items, str(response.url))

    return Skill(
        name="read_feed",
        when=(
            "Lê um feed RSS ou Atom e lista os itens recentes com data e link. "
            "Use quando a pessoa passar o endereço de um feed ou de um blog."
        ),
        risk="leitura",
        needs_approval=False,
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Endereço do feed RSS ou Atom."},
                "limit": {"type": "integer", "description": "Quantos itens, no máximo 12."},
            },
            "required": ["url"],
        },
        run=run,
    )


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(node: ET.Element, name: str) -> ET.Element | None:
    for child in list(node):
        if _local(child.tag) == name:
            return child
    return None


def _text(node: ET.Element | None) -> str:
    if node is None or node.text is None:
        return ""
    return " ".join(node.text.split())


def _link(node: ET.Element) -> str:
    for child in list(node):
        if _local(child.tag) != "link":
            continue
        href = child.attrib.get("href")
        if href:
            return href.strip()
        if child.text and child.text.strip():
            return " ".join(child.text.split())
    return ""
