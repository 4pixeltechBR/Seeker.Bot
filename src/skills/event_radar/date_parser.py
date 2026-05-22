"""
Parser de datas em português para eventos brasileiros.

Extrai mês (1–12) de strings livres como:
  "29 de abril a 03 de maio de 2026"
  "Julho de 2026 (Aproximada)"
  "08/12/2026"
  "Segundo semestre de 2026"
  "Data a confirmar"

Campos adicionados ao evento:
  mes       — int 1–12 ou None
  mes_fim   — int 1–12 ou None (quando o evento cruza meses)
  precisao  — "exata" | "mensal" | "semestral" | "indeterminada"
"""

import re

_MESES = {
    "janeiro": 1, "jan": 1,
    "fevereiro": 2, "fev": 2,
    "março": 3, "marco": 3, "mar": 3,
    "abril": 4, "abr": 4,
    "maio": 5,
    "junho": 6, "jun": 6,
    "julho": 7, "jul": 7,
    "agosto": 8, "ago": 8,
    "setembro": 9, "set": 9,
    "outubro": 10, "out": 10,
    "novembro": 11, "nov": 11,
    "dezembro": 12, "dez": 12,
}

_RE_DIA_MES = re.compile(
    r"\b\d{1,2}(?:º|°|o)?\s*(?:de\s+)?(" + "|".join(_MESES) + r")",
    re.IGNORECASE,
)
_RE_MES_ISOLADO = re.compile(
    r"\b(" + "|".join(_MESES) + r")\b",
    re.IGNORECASE,
)
_RE_SLASH = re.compile(r"\b(\d{1,2})/(\d{1,2})/\d{2,4}\b")
_RE_SEMESTRE1 = re.compile(r"primeiro\s+semestre|1[oº°]\s*semestre", re.IGNORECASE)
_RE_SEMESTRE2 = re.compile(r"segundo\s+semestre|2[oº°]\s*semestre", re.IGNORECASE)


def _find_all_months(text: str) -> list[int]:
    """Retorna todos os meses encontrados no texto (sem duplicatas, em ordem)."""
    text_lower = text.lower()
    found = []

    # DD/MM/YYYY
    for m in _RE_SLASH.finditer(text_lower):
        mes = int(m.group(2))
        if 1 <= mes <= 12 and mes not in found:
            found.append(mes)

    # "DD de MONTH" e "MONTH de YYYY"
    for m in _RE_DIA_MES.finditer(text_lower):
        nome = m.group(1).lower()
        mes = _MESES.get(nome)
        if mes and mes not in found:
            found.append(mes)

    # mês isolado (sem dia antes)
    for m in _RE_MES_ISOLADO.finditer(text_lower):
        nome = m.group(1).lower()
        mes = _MESES.get(nome)
        if mes and mes not in found:
            found.append(mes)

    return found


def parse_date(data_estimada: str) -> dict:
    """
    Retorna {"mes": int|None, "mes_fim": int|None, "precisao": str}.
    """
    if not data_estimada:
        return {"mes": None, "mes_fim": None, "precisao": "indeterminada"}

    text = data_estimada.strip()

    # Semestre sem mês específico
    if _RE_SEMESTRE1.search(text):
        return {"mes": 1, "mes_fim": 6, "precisao": "semestral"}
    if _RE_SEMESTRE2.search(text):
        return {"mes": 7, "mes_fim": 12, "precisao": "semestral"}

    meses = _find_all_months(text)

    if not meses:
        return {"mes": None, "mes_fim": None, "precisao": "indeterminada"}

    mes = meses[0]
    mes_fim = meses[-1] if len(meses) > 1 else None

    # Precisão: tem dia explícito → exata; só mês → mensal
    tem_dia = bool(_RE_DIA_MES.search(text.lower())) or bool(_RE_SLASH.search(text))
    precisao = "exata" if tem_dia else "mensal"

    return {"mes": mes, "mes_fim": mes_fim, "precisao": precisao}


def enrich_event(event: dict) -> dict:
    """Adiciona mes/mes_fim/precisao a um evento (in-place, retorna o mesmo dict)."""
    parsed = parse_date(event.get("data_estimada", ""))
    event.update(parsed)
    return event
