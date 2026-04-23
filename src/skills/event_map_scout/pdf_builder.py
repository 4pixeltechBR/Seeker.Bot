"""
Seeker.Bot — Event Map Scout PDF Builder (Lumen Edition)
src/skills/event_map_scout/pdf_builder.py

Layout profissional com cards estruturados, seçoes categorizadas e hierarquia visual clara.
"""

import json
import logging
import os
from datetime import datetime
from fpdf import FPDF

log = logging.getLogger("seeker.event_map.pdf")
OUTPUT_DIR = os.path.join(os.getcwd(), "data", "event_maps")

# ── Paleta de Cores ────────────────────────────────────────────────
C_BRAND_BG    = (15, 40, 80)      # Azul marinho: header principal
C_BRAND_ACCENT= (0, 130, 200)     # Azul vivo: barras de seção
C_SCORE_HIGH  = (34, 139, 34)     # Verde: score >= 8
C_SCORE_MID   = (210, 140, 0)     # Âmbar: score 6-7
C_SCORE_LOW   = (180, 60, 60)     # Vermelho suave: score < 6
C_CARD_BG     = (248, 250, 252)   # Cinza quase branco: fundo do card
C_CARD_BORDER = (210, 220, 235)   # Cinza azulado: borda do card
C_TEXT_MAIN   = (20, 30, 50)      # Quase preto
C_TEXT_LABEL  = (80, 100, 130)    # Cinza azulado: rótulos
C_TEXT_MUTED  = (130, 145, 165)   # Cinza: texto secundário
C_ROW_ALT     = (235, 242, 252)   # Azul muito claro: zebra da tabela
C_WHITE       = (255, 255, 255)
C_DIVIDER     = (220, 225, 235)


def _safe(text) -> str:
    """Converte para string segura em latin-1."""
    if text is None or str(text).lower() in ("none", "null", ""):
        return ""
    replacements = {
        "\u2014": "-", "\u2013": "-", "\u201c": '"', "\u201d": '"',
        "\u2018": "'", "\u2019": "'", "\u2026": "...", "\u2022": "-",
        "\u00b7": "-", "\u2192": "->", "\u2713": "OK", "\u2717": "X",
        "\u2764": "<3",
    }
    s = str(text)
    for old, new in replacements.items():
        s = s.replace(old, new)
    return s.encode("latin-1", "ignore").decode("latin-1").strip()


def _score_color(score):
    try:
        s = float(score)
        if s >= 8: return C_SCORE_HIGH
        if s >= 6: return C_SCORE_MID
        return C_SCORE_LOW
    except:
        return C_TEXT_MUTED


def _score_label(score):
    try:
        s = float(score)
        if s >= 8: return "ALTA"
        if s >= 6: return "MEDIA"
        return "BAIXA"
    except:
        return "?"


CATEGORY_LABELS = {
    "AGROPECUARIO":       "Agropecuario e Rodeio",
    "AGRO_PREMIUM":       "Agro Premium (Vaquejada / Leilao)",
    "RELIGIOSO":          "Religioso e Festas de Padroeiro",
    "MUNICIPAL":          "Eventos Municipais",
    "JUNINO":             "Festas Juninas e Arraiais",
    "SHOW_FESTIVAL":      "Shows e Festivais",
    "GOVERNAMENTAL":      "Licitacoes e Contratos Publicos",
    "CORPORATIVO":        "Corporativo e B2B",
    "FESTAS_PARTICULARES":"Festas Particulares",
    "FESTAS_SAZONAIS":    "Festas Sazonais (Reveillon / Pool Party)",
    "CULTURAL":           "Cultural e Gastronomico",
    "ESPORTIVO":          "Esportivo e Motos",
    "TURISMO_E_PRIVADO":  "Turismo Privado (Resorts / Parques)",
    "BARES_E_VIDA_NOTURNA":"Bares e Vida Noturna",
    "DATAS_COMEMORATIVAS":"Datas Comemorativas",
    "EDUCACIONAL":        "Escolas e Formaturas",
    "META_INTELIGENCIA":  "Inteligencia de Mercado",
    "REDES_SOCIAIS_BROAD":"Redes Sociais (Broad)",
}


class EventMapPDF(FPDF):
    def __init__(self, city_name: str, state_name: str):
        super().__init__()
        self.city_name = city_name
        self.state_name = state_name
        self.set_auto_page_break(auto=True, margin=20)
        self.set_margins(14, 14, 14)

    def header(self):
        # Barra de fundo marinho
        self.set_fill_color(*C_BRAND_BG)
        self.rect(0, 0, 210, 28, "F")

        # Título principal
        self.set_y(5)
        self.set_font("Helvetica", "B", 17)
        self.set_text_color(*C_WHITE)
        self.cell(0, 8, f"Mapa Comercial de Eventos", align="C", new_x="LMARGIN", new_y="NEXT")

        # Subtítulo com cidade
        self.set_font("Helvetica", "", 11)
        self.set_text_color(180, 210, 240)
        date_str = datetime.now().strftime("%d/%m/%Y")
        self.cell(0, 6, f"{self.city_name} - {self.state_name}  |  Gerado em {date_str}  |  Event Map Scout", align="C", new_x="LMARGIN", new_y="NEXT")

        self.set_text_color(*C_TEXT_MAIN)
        self.ln(8)

    def footer(self):
        self.set_y(-13)
        self.set_fill_color(*C_BRAND_BG)
        self.rect(0, self.get_y() - 2, 210, 16, "F")
        self.set_font("Helvetica", "", 8)
        self.set_text_color(160, 185, 215)
        self.cell(0, 10, f"Event Map Scout  |  Pagina {self.page_no()}/{{nb}}  |  Confidencial - Uso Interno", align="C")

    def section_header(self, title: str, count: int):
        """Barra de secao azul vivo com nome da categoria."""
        self.ln(4)
        self.set_fill_color(*C_BRAND_ACCENT)
        self.set_text_color(*C_WHITE)
        self.set_font("Helvetica", "B", 10)
        self.rect(14, self.get_y(), 182, 7, "F")
        self.set_x(16)
        label = CATEGORY_LABELS.get(title, title.replace("_", " ").title())
        self.cell(140, 7, _safe(label), new_x="RIGHT")
        self.cell(40, 7, f"{count} evento(s)", align="R")
        self.ln(9)

    def event_card(self, ev: dict, index: int):
        """Card visual de um evento."""
        nome       = _safe(ev.get("nome_evento", "Evento Desconhecido"))
        categoria  = _safe(ev.get("categoria", ""))
        periodo    = _safe(ev.get("periodo", ""))
        porte      = _safe(ev.get("porte_estimado", "")).capitalize()
        score      = ev.get("score_oportunidade", 0)
        decisor    = _safe(ev.get("decisor_nome", ""))
        cargo      = _safe(ev.get("decisor_cargo", ""))
        telefone   = _safe(ev.get("telefone", ""))
        instagram  = _safe(ev.get("instagram", ""))
        valor      = _safe(ev.get("valor_contrato_publico", ""))
        historico  = _safe(ev.get("historico_anos", ""))
        sinais     = _safe(ev.get("sinais_contratacao", ""))

        # Estima altura do card antes de adicionar
        # (se não couber na página, o auto_page_break cuida)
        card_x = self.l_margin
        card_w = 182
        card_h_min = 35
        
        if self.get_y() + card_h_min > self.page_break_trigger:
            self.add_page()

        y_start = self.get_y()

        # Fundo do card
        self.set_fill_color(*C_CARD_BG)
        self.set_draw_color(*C_CARD_BORDER)
        self.set_line_width(0.3)
        self.rect(card_x, y_start, card_w, card_h_min, "FD")  # Será sobreposto

        # Barra lateral esquerda colorida (cor do score)
        sc = _score_color(score)
        self.set_fill_color(*sc)
        self.rect(card_x, y_start, 3, card_h_min, "F")

        # Número do card (index)
        self.set_xy(card_x + 4, y_start + 2)
        self.set_font("Helvetica", "", 7)
        self.set_text_color(*C_TEXT_MUTED)
        self.cell(10, 4, f"#{index:02d}", new_x="RIGHT")

        # Nome do evento
        self.set_font("Helvetica", "B", 11)
        self.set_text_color(*C_TEXT_MAIN)
        self.set_xy(card_x + 14, y_start + 2)
        self.cell(130, 6, nome[:65], new_x="LMARGIN", new_y="NEXT")

        # Score badge
        self.set_xy(card_x + 155, y_start + 2)
        self.set_fill_color(*sc)
        self.set_text_color(*C_WHITE)
        self.set_font("Helvetica", "B", 8)
        self.cell(27, 6, f"Score: {score}  {_score_label(score)}", align="C", fill=True, border=0)

        # Linha 2 — Periodo + Porte + Historico
        self.set_xy(card_x + 5, y_start + 10)
        self.set_text_color(*C_TEXT_LABEL)
        self.set_font("Helvetica", "B", 8)
        self.cell(18, 4.5, "Periodo:", new_x="RIGHT")
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*C_TEXT_MAIN)
        self.cell(45, 4.5, periodo or "Nao identificado", new_x="RIGHT")

        self.set_font("Helvetica", "B", 8)
        self.set_text_color(*C_TEXT_LABEL)
        self.cell(16, 4.5, "Porte:", new_x="RIGHT")
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*C_TEXT_MAIN)
        self.cell(30, 4.5, porte or "-", new_x="RIGHT")

        if historico:
            self.set_font("Helvetica", "B", 8)
            self.set_text_color(*C_TEXT_LABEL)
            self.cell(22, 4.5, "Historico:", new_x="RIGHT")
            self.set_font("Helvetica", "", 8)
            self.set_text_color(*C_TEXT_MAIN)
            self.cell(55, 4.5, historico[:40], new_x="LMARGIN", new_y="NEXT")
        else:
            self.ln(4.5)

        # Linha 3 — Contato / Decisor
        y_row = self.get_y()
        self.set_xy(card_x + 5, y_row)
        if decisor:
            self.set_font("Helvetica", "B", 8)
            self.set_text_color(*C_TEXT_LABEL)
            self.cell(20, 4.5, "Decisor:", new_x="RIGHT")
            self.set_font("Helvetica", "", 8)
            self.set_text_color(*C_TEXT_MAIN)
            contact = decisor
            if cargo:
                contact += f" ({cargo})"
            self.cell(120, 4.5, _safe(contact)[:70], new_x="LMARGIN", new_y="NEXT")

        # Linha 4 — Telefone + Instagram
        y_row = self.get_y()
        self.set_xy(card_x + 5, y_row)
        has_contact = telefone or instagram or valor

        if telefone:
            self.set_font("Helvetica", "B", 8)
            self.set_text_color(*C_TEXT_LABEL)
            self.cell(16, 4.5, "Telefone:", new_x="RIGHT")
            self.set_font("Helvetica", "", 8)
            self.set_text_color(*C_TEXT_MAIN)
            self.cell(45, 4.5, telefone, new_x="RIGHT")

        if instagram:
            self.set_font("Helvetica", "B", 8)
            self.set_text_color(*C_TEXT_LABEL)
            self.cell(18, 4.5, "Instagram:", new_x="RIGHT")
            self.set_font("Helvetica", "", 8)
            self.set_text_color(*C_BRAND_ACCENT)
            self.cell(60, 4.5, instagram[:40], new_x="RIGHT")

        if valor:
            self.set_font("Helvetica", "B", 8)
            self.set_text_color(*C_TEXT_LABEL)
            self.cell(20, 4.5, "Valor Pub.:", new_x="RIGHT")
            self.set_font("Helvetica", "B", 8)
            self.set_text_color(*C_SCORE_HIGH)
            self.cell(35, 4.5, valor[:25], new_x="LMARGIN", new_y="NEXT")
        elif has_contact:
            self.ln(4.5)
        else:
            self.ln(2)

        # Linha 5 — Sinais de Contratacao (se existir)
        if sinais:
            y_row = self.get_y()
            self.set_xy(card_x + 5, y_row)
            self.set_font("Helvetica", "I", 7.5)
            self.set_text_color(*C_TEXT_MUTED)
            try:
                self.multi_cell(card_w - 10, 3.8, _safe(sinais)[:180])
            except Exception:
                pass

        self.ln(4)

        # Redraw card border over correct height
        y_end = self.get_y()
        h = y_end - y_start
        self.set_fill_color(*C_CARD_BG)
        self.set_draw_color(*C_CARD_BORDER)
        self.set_line_width(0.3)
        self.rect(card_x, y_start, card_w, h, "D")
        self.set_fill_color(*sc)
        self.rect(card_x, y_start, 3, h, "F")

        self.ln(2)

    def summary_box(self, total: int, high: int, mid: int, categories: int):
        """Caixa de resumo executivo no topo."""
        self.set_fill_color(*C_BRAND_BG)
        self.set_text_color(*C_WHITE)
        self.set_font("Helvetica", "B", 9)

        box_y = self.get_y()
        self.rect(14, box_y, 182, 16, "F")

        cols = [
            ("Total de Eventos", str(total)),
            ("Alta Prioridade",  str(high)),
            ("Media Prioridade", str(mid)),
            ("Categorias",       str(categories)),
        ]
        col_w = 182 / len(cols)
        for i, (label, val) in enumerate(cols):
            self.set_xy(14 + i * col_w, box_y + 1)
            self.set_font("Helvetica", "", 7)
            self.set_text_color(160, 190, 220)
            self.cell(col_w, 4, label, align="C", new_x="RIGHT" if i < len(cols) - 1 else "LMARGIN", new_y="NEXT" if i == len(cols) - 1 else "LAST")
            self.set_xy(14 + i * col_w, box_y + 6)
            self.set_font("Helvetica", "B", 13)
            self.set_text_color(*C_WHITE)
            self.cell(col_w, 7, val, align="C")

        self.ln(20)

    def top_opportunities_table(self, events: list):
        """Tabela visual Top 10 Oportunidades."""
        top = sorted(events, key=lambda e: float(e.get("score_oportunidade", 0) or 0), reverse=True)[:10]
        if not top:
            return

        # Cabeçalho da seção
        self.set_fill_color(*C_BRAND_BG)
        self.set_text_color(*C_WHITE)
        self.set_font("Helvetica", "B", 10)
        self.rect(14, self.get_y(), 182, 7, "F")
        self.set_x(16)
        self.cell(0, 7, "Top 10 - Maiores Oportunidades Previstas", new_x="LMARGIN", new_y="NEXT")
        self.ln(1)

        # Cabeçalho da tabela
        headers = ["#", "Evento", "Periodo", "Porte", "Score"]
        col_w   = [8, 90, 38, 22, 20]

        self.set_fill_color(*C_BRAND_ACCENT)
        self.set_text_color(*C_WHITE)
        self.set_font("Helvetica", "B", 8)
        self.set_x(14)
        for h, w in zip(headers, col_w):
            self.cell(w, 6, h, border=0, fill=True, align="C")
        self.ln(6)

        # Linhas da tabela
        for i, ev in enumerate(top):
            alt = (i % 2 == 1)
            fill_bg = C_ROW_ALT if alt else C_WHITE

            self.set_fill_color(*fill_bg)
            self.set_text_color(*C_TEXT_MAIN)
            self.set_font("Helvetica", "", 8)
            self.set_x(14)

            nome    = _safe(ev.get("nome_evento", ""))[:45]
            periodo = _safe(ev.get("periodo", ""))[:20]
            porte   = _safe(ev.get("porte_estimado", "")).capitalize()[:12]
            score   = ev.get("score_oportunidade", 0)
            sc_col  = _score_color(score)

            self.cell(col_w[0], 5.5, str(i + 1), fill=True, align="C")
            self.cell(col_w[1], 5.5, nome, fill=True)
            self.cell(col_w[2], 5.5, periodo, fill=True)
            self.cell(col_w[3], 5.5, porte, fill=True, align="C")

            # Score colorido
            self.set_fill_color(*sc_col)
            self.set_text_color(*C_WHITE)
            self.set_font("Helvetica", "B", 8)
            self.cell(col_w[4], 5.5, str(score), fill=True, align="C")

            self.ln(5.5)
            # Restaura
            self.set_fill_color(*fill_bg)
            self.set_text_color(*C_TEXT_MAIN)
            self.set_font("Helvetica", "", 8)

        self.ln(8)


# ── Função principal ──────────────────────────────────────────────

def build_event_map_pdf(report_md: str, cidade: str, estado: str,
                         events: list = None) -> str:
    """
    Gera o PDF estruturado do mapa de eventos.
    `events` = lista de dicts do banco de dados (preferido).
    `report_md` = fallback markdown caso events nao seja passado.
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    safe_city = cidade.replace(" ", "_").replace("/", "").replace("\\", "")
    pdf_path  = os.path.join(OUTPUT_DIR, f"Map_{safe_city}_{estado}.pdf")

    # Se não receber events, tenta parsear do markdown (fallback simples)
    if not events:
        events = _parse_events_from_md(report_md)

    try:
        pdf = EventMapPDF(cidade, estado)
        pdf.alias_nb_pages()
        pdf.add_page()

        # ── Caixa de Resumo Executivo ──
        high = sum(1 for e in events if float(e.get("score_oportunidade", 0) or 0) >= 8)
        mid  = sum(1 for e in events if 6 <= float(e.get("score_oportunidade", 0) or 0) < 8)
        cats = len(set(e.get("categoria", "") for e in events))
        pdf.summary_box(len(events), high, mid, cats)

        # ── Tabela Top Oportunidades ──
        pdf.top_opportunities_table(events)

        # ── Cards por Categoria ──
        by_cat = {}
        for ev in events:
            cat = ev.get("categoria", "GERAL")
            by_cat.setdefault(cat, []).append(ev)

        # Ordena categorias por score medio descendente
        sorted_cats = sorted(
            by_cat.items(),
            key=lambda kv: -sum(float(e.get("score_oportunidade", 0) or 0) for e in kv[1]) / max(len(kv[1]), 1)
        )

        global_index = 1
        for cat_name, cat_events in sorted_cats:
            cat_sorted = sorted(cat_events, key=lambda e: float(e.get("score_oportunidade", 0) or 0), reverse=True)
            pdf.section_header(cat_name, len(cat_sorted))
            for ev in cat_sorted:
                pdf.event_card(ev, global_index)
                global_index += 1

        pdf.output(pdf_path)
        log.info(f"[pdf] PDF Lumen gerado: {pdf_path} ({len(events)} eventos)")
        return pdf_path

    except Exception as e:
        log.error(f"[pdf] Erro ao gerar PDF de {cidade}: {e}")
        return ""


def _parse_events_from_md(md: str) -> list:
    """Extração mínima de fallback — não usado se events vier do DB."""
    return []
