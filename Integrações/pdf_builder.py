"""
Seeker.Bot — SenseNews PDF Builder
src/skills/sense_news/pdf_builder.py

Converte relatório Markdown em PDF usando markdown + fpdf2.
fpdf2 é leve, sem dependência de GTK/WeasyPrint, funciona em Windows e Linux.

Dependência: pip install fpdf2
"""

import logging
import os
from datetime import datetime

from fpdf import FPDF

log = logging.getLogger("seeker.sensenews.pdf")

OUTPUT_DIR = os.path.join(os.getcwd(), "data", "sense_news")


class SenseNewsPDF(FPDF):
    """PDF customizado com header/footer do SenseNews."""

    def __init__(self, date_label: str):
        super().__init__()
        self.date_label = date_label
        # Fonte padrão — evita dependência de fontes externas
        self.set_auto_page_break(auto=True, margin=20)

    def header(self):
        self.set_font("Helvetica", "B", 14)
        self.set_text_color(30, 30, 30)
        self.cell(0, 10, f"SenseNews - {self.date_label}", align="C", new_x="LMARGIN", new_y="NEXT")
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(120, 120, 120)
        self.cell(0, 5, "Gerado automaticamente pelo Seeker.Bot", align="C", new_x="LMARGIN", new_y="NEXT")
        self.ln(5)
        # Linha separadora
        self.set_draw_color(200, 200, 200)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, f"Pagina {self.page_no()}/{{nb}}", align="C")


def build_sense_news_pdf(
    report_md: str,
    analyses: list[dict],
    date_label: str,
) -> str:
    """
    Converte relatório markdown em PDF.

    Args:
        report_md: relatório em markdown gerado pelo LLM
        analyses: lista de análises brutas (fallback se md falhar)
        date_label: ex: "02/04/2026"

    Returns:
        Caminho absoluto do PDF gerado.
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    date_file = datetime.now().strftime("%Y-%m-%d")
    pdf_path = os.path.join(OUTPUT_DIR, f"SenseNews_{date_file}.pdf")

    try:
        pdf = SenseNewsPDF(date_label)
        pdf.alias_nb_pages()
        pdf.add_page()

        # Processa markdown linha por linha
        _render_markdown(pdf, report_md)

        pdf.output(pdf_path)
        log.info(f"[sensenews] PDF gerado: {pdf_path}")
        return pdf_path

    except Exception as e:
        log.error(f"[sensenews] Falha ao gerar PDF: {e}")
        # Fallback: gera PDF simples sem formatação markdown
        return _fallback_pdf(analyses, date_label, pdf_path)


def _render_markdown(pdf: FPDF, md_text: str):
    """Renderiza markdown básico no PDF (headers, bold, italic, parágrafos)."""
    lines = md_text.split("\n")

    for line in lines:
        stripped = line.strip()

        if not stripped:
            pdf.ln(3)
            continue

        # H1
        if stripped.startswith("# "):
            pdf.set_font("Helvetica", "B", 16)
            pdf.set_text_color(20, 20, 20)
            text = stripped[2:].strip()
            text = _clean_emoji(text)
            pdf.multi_cell(0, 8, text)
            pdf.ln(3)
            continue

        # H2
        if stripped.startswith("## "):
            pdf.set_font("Helvetica", "B", 13)
            pdf.set_text_color(40, 40, 40)
            text = stripped[3:].strip()
            text = _clean_emoji(text)
            pdf.multi_cell(0, 7, text)
            pdf.ln(2)
            continue

        # H3
        if stripped.startswith("### "):
            pdf.set_font("Helvetica", "B", 11)
            pdf.set_text_color(60, 60, 60)
            text = stripped[4:].strip()
            text = _clean_emoji(text)
            pdf.multi_cell(0, 6, text)
            pdf.ln(1)
            continue

        # Linha separadora
        if stripped in ("---", "***", "___"):
            pdf.set_draw_color(200, 200, 200)
            pdf.line(10, pdf.get_y(), 200, pdf.get_y())
            pdf.ln(3)
            continue

        # Parágrafo normal
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(50, 50, 50)

        # Remove markdown inline básico pra texto limpo
        text = _strip_inline_markdown(stripped)
        text = _clean_emoji(text)

        pdf.multi_cell(0, 5, text)
        pdf.ln(1)


def _strip_inline_markdown(text: str) -> str:
    """Remove **bold** e *italic* do texto."""
    import re
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return text


def _clean_emoji(text: str) -> str:
    """Remove emojis que fpdf2 não renderiza com fontes padrão."""
    import re
    emoji_pattern = re.compile(
        "["
        "\U0001f600-\U0001f64f"
        "\U0001f300-\U0001f5ff"
        "\U0001f680-\U0001f6ff"
        "\U0001f1e0-\U0001f1ff"
        "\U00002702-\U000027b0"
        "\U000024c2-\U0001f251"
        "\U0001f900-\U0001f9ff"
        "\U0001fa00-\U0001fa6f"
        "\U0001fa70-\U0001faff"
        "\U00002600-\U000026ff"
        "]+",
        flags=re.UNICODE,
    )
    return emoji_pattern.sub("", text).strip()


def _fallback_pdf(
    analyses: list[dict], date_label: str, pdf_path: str
) -> str:
    """Gera PDF simples como fallback."""
    try:
        pdf = SenseNewsPDF(date_label)
        pdf.alias_nb_pages()
        pdf.add_page()

        pdf.set_font("Helvetica", "B", 14)
        pdf.cell(0, 10, f"SenseNews - {date_label}", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(5)

        for a in analyses:
            pdf.set_font("Helvetica", "B", 11)
            niche = a.get("niche", "?")
            title = _clean_emoji(a.get("title", "Sem titulo"))
            pdf.multi_cell(0, 6, f"[{niche}] {title}")

            pdf.set_font("Helvetica", "", 10)
            analysis = _clean_emoji(a.get("analysis", ""))
            pdf.multi_cell(0, 5, analysis)

            impact = _clean_emoji(a.get("impact", ""))
            pdf.set_font("Helvetica", "I", 9)
            pdf.multi_cell(0, 5, f"Impacto: {impact}")
            pdf.ln(3)

        pdf.output(pdf_path)
        log.info(f"[sensenews] PDF fallback gerado: {pdf_path}")
        return pdf_path
    except Exception as e:
        log.error(f"[sensenews] Falha no fallback PDF: {e}")
        return ""
