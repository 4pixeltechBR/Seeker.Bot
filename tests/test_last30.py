from datetime import datetime, timezone

from seeker.skills.last30 import format_brief, gather, last30_skill, parse_github, parse_hn, parse_polymarket, parse_reddit
from seeker.skills.research import NO_SOURCE

NOW = datetime(2026, 10, 7, tzinfo=timezone.utc)

HN = '{"hits":[{"title":"Agentes locais","url":"https://ex.test/hn","points":120,"objectID":"1"}]}'
REDDIT = """<?xml version="1.0"?><rss><channel><item>
<title>Thread sobre agentes</title><link>https://www.reddit.com/r/x/1</link>
</item></channel></rss>"""
GITHUB = '{"items":[{"full_name":"ana/agentes","html_url":"https://github.com/ana/agentes","stargazers_count":40}]}'
POLY = '{"events":[{"title":"Agentes em 2026","slug":"agentes-2026","volume":9000}]}'


def test_cada_fonte_vira_item_com_link():
    assert parse_hn(HN)[0]["score"] == 120
    assert parse_hn('{"hits":[{"title":"Sem url","objectID":"9"}]}')[0]["url"].endswith("item?id=9")
    assert parse_reddit(REDDIT)[0]["source"] == "Reddit"
    assert parse_github(GITHUB)[0]["unit"] == "estrelas"
    assert "polymarket.com/event/agentes-2026" in parse_polymarket(POLY)[0]["url"]


def test_brief_ordena_por_engajamento_e_cita_fonte():
    def fetch(url: str):
        if "algolia" in url:
            return 200, HN
        if "reddit" in url:
            return 200, REDDIT
        if "github" in url:
            return 200, GITHUB
        if "polymarket" in url:
            return 200, POLY
        return 500, ""

    hits, notes = gather(fetch, "agentes", NOW)
    text = format_brief("agentes", hits, notes)
    assert text.index("120 pontos") < text.index("estrelas")
    assert "Fontes:" in text
    assert "https://ex.test/hn" in text
    assert notes == []


def test_sem_fonte_nao_vira_fato():
    skill = last30_skill(lambda url: (503, ""))
    assert skill.run({"query": "agentes"}) == NO_SOURCE
    assert skill.needs_approval is False
    assert skill.run({"query": "  "}) == "Diga o tema dos últimos 30 dias."
