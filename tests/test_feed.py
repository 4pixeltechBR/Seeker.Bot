import httpx

from seeker.browser import PageReader
from seeker.skills.feed import parse_feed, read_feed_skill


def _public(host, port, *rest):
    return [(0, "", "", "", ("1.1.1.1", 0))]


RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel>
<title>Diário</title>
<item>
  <title>Primeira</title>
  <link>https://ex.test/1</link>
  <pubDate>Mon, 05 Oct 2026 10:00:00 GMT</pubDate>
  <description>&lt;p&gt;Texto do item.&lt;/p&gt;</description>
</item>
<item><title>Segunda</title><link>https://ex.test/2</link></item>
</channel></rss>
"""

ATOM = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Atom</title>
  <entry>
    <title>Nota</title>
    <link href="https://ex.test/n"/>
    <updated>2026-10-05T12:00:00Z</updated>
    <summary>Resumo curto.</summary>
  </entry>
</feed>
"""


def test_rss_e_atom_viram_lista():
    title, items = parse_feed(RSS, 8)
    assert title == "Diário"
    assert items[0]["title"] == "Primeira"
    assert items[0]["summary"] == "Texto do item."
    assert len(items) == 2
    atom_title, atom_items = parse_feed(ATOM, 8)
    assert atom_title == "Atom"
    assert atom_items[0]["link"] == "https://ex.test/n"
    assert atom_items[0]["when"] == "2026-10-05T12:00:00Z"


def test_feed_lista_itens_e_recusa_local():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=RSS)

    skill = read_feed_skill(PageReader(httpx.Client(transport=httpx.MockTransport(handler)), resolve=_public))
    text = skill.run({"url": "https://ex.test/rss", "limit": 1})
    assert "Diário" in text
    assert "Primeira" in text
    assert "Segunda" not in text
    assert skill.needs_approval is False
    assert "fora" in skill.run({"url": "http://127.0.0.1/rss"})


def test_jina_falha_e_a_pagina_abre_direto():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if "r.jina.ai" in str(request.url):
            return httpx.Response(503, text="ocupado")
        return httpx.Response(200, text="<p>boletim direto</p>")

    reader = PageReader(httpx.Client(transport=httpx.MockTransport(handler)), resolve=_public)
    text = reader.read("https://ex.test/dia")
    assert "boletim direto" in text
    assert "Leitura direta." in text
    assert len(seen) == 2


def test_jina_devolve_markdown():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="# Título\n\nParágrafo limpo.")

    reader = PageReader(httpx.Client(transport=httpx.MockTransport(handler)), resolve=_public)
    text = reader.read("https://ex.test/dia")
    assert "Parágrafo limpo." in text
    assert "Leitura limpa." in text
    assert "Fonte: https://ex.test/dia" in text
