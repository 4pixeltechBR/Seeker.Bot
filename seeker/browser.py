"""Lê uma página e devolve o texto com a fonte. Enviar formulário pede licença."""

from __future__ import annotations

import ipaddress
import socket
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx

from seeker.skills.contract import Skill

CAP = 8000


class BrowserError(Exception):
    pass


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._skip = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript"}:
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript"} and self._skip:
            self._skip -= 1
        if tag in {"p", "div", "br", "li", "h1", "h2", "h3", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._skip:
            return
        text = " ".join(data.split())
        if text:
            self.parts.append(text)


def page_text(html: str) -> str:
    parser = _Text()
    parser.feed(html or "")
    lines = []
    for part in parser.parts:
        if part == "\n":
            if lines and lines[-1] != "":
                lines.append("")
            continue
        lines.append(part)
    return "\n".join(lines).strip()


def check_url(url: str, resolve=socket.getaddrinfo) -> str:
    parsed = urlparse((url or "").strip())
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or not host:
        raise BrowserError("Só leio páginas http ou https.")
    if host in {"localhost", "localhost."} or host.endswith(".local"):
        raise BrowserError("Essa página fica fora.")
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            infos = resolve(host, None)
        except OSError as exc:
            raise BrowserError("Não encontrei esse endereço.") from exc
        addresses = []
        for info in infos:
            try:
                addresses.append(ipaddress.ip_address(info[4][0]))
            except ValueError:
                continue
    for ip in addresses:
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise BrowserError("Essa página fica fora.")
    if not addresses:
        raise BrowserError("Não encontrei esse endereço.")
    return (url or "").strip()


def format_page(text: str, source: str, status: int) -> str:
    body = " ".join((text or "").split())
    if status >= 400:
        return f"A página não abriu (HTTP {status}).\n\nFonte: {source}"
    if not body:
        return f"A página não tinha texto.\n\nFonte: {source}"
    if len(body) > CAP:
        body = body[:CAP] + "…"
    return f"{body}\n\nFonte: {source}"


class PageReader:
    def __init__(self, client: httpx.Client, resolve=socket.getaddrinfo):
        self.client = client
        self.resolve = resolve

    def read(self, url: str) -> str:
        safe = check_url(url, self.resolve)
        cleaned = self._jina(safe)
        if cleaned:
            return cleaned
        response = self._send("GET", safe, None)
        check_url(str(response.url), self.resolve)
        return format_page(page_text(response.text), str(response.url), response.status_code) + "\nLeitura direta."

    def submit(self, url: str, fields: dict) -> str:
        safe = check_url(url, self.resolve)
        data = {str(key): str(value) for key, value in fields.items()}
        response = self._send("POST", safe, data)
        check_url(str(response.url), self.resolve)
        return format_page(page_text(response.text), str(response.url), response.status_code)

    def _jina(self, url: str) -> str | None:
        target = "https://r.jina.ai/" + url
        try:
            check_url(target, self.resolve)
            response = self.client.request(
                "GET",
                target,
                headers={"Accept": "text/markdown", "User-Agent": "Seeker"},
                follow_redirects=True,
                timeout=20.0,
            )
            check_url(str(response.url), self.resolve)
        except (BrowserError, httpx.HTTPError):
            return None
        if response.status_code >= 400:
            return None
        text = (response.text or "").strip()
        if not text:
            return None
        head = text[:400].casefold()
        if "<html" in head or "<p" in head or "<div" in head:
            text = page_text(text)
        if not text:
            return None
        return format_page(text, url, 200) + "\nLeitura limpa."

    def _send(self, method: str, url: str, data: dict | None) -> httpx.Response:
        try:
            return self.client.request(method, url, data=data, follow_redirects=True, timeout=20.0)
        except httpx.HTTPError as exc:
            raise BrowserError("A página não abriu.") from exc


def read_page_skill(reader: PageReader) -> Skill:
    def run(arguments: dict) -> str:
        try:
            return reader.read(str(arguments.get("url") or ""))
        except BrowserError as exc:
            return str(exc)

    return Skill(
        name="read_page",
        when="Abre uma página http ou https e devolve o texto com a fonte. Use para ler, não para clicar nem preencher.",
        risk="leitura",
        needs_approval=False,
        parameters={
            "type": "object",
            "properties": {"url": {"type": "string", "description": "Endereço completo da página."}},
            "required": ["url"],
        },
        run=run,
    )


def submit_form_skill(reader: PageReader) -> Skill:
    def run(arguments: dict) -> str:
        fields = arguments.get("fields")
        if not isinstance(fields, dict) or not fields:
            return "Diga os campos do formulário."
        try:
            return reader.submit(str(arguments.get("url") or ""), fields)
        except BrowserError as exc:
            return str(exc)

    return Skill(
        name="submit_form",
        when=(
            "Envia um formulário. É alto risco: pare e peça autorização antes. "
            "Mostre o endereço e os campos. Não use para só ler uma página."
        ),
        risk="altera",
        needs_approval=True,
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Endereço que recebe o formulário."},
                "fields": {
                    "type": "object",
                    "description": "Campos e valores, exatamente como serão enviados.",
                },
            },
            "required": ["url", "fields"],
        },
        run=run,
    )
