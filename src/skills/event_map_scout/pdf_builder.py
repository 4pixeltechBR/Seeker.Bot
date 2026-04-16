"""
Seeker.Bot — Event Map Scout PDF Builder
src/skills/event_map_scout/pdf_builder.py
"""

import logging
import os
import re
from datetime import datetime
from fpdf import FPDF

def _strip_inline_markdown(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return text

def _clean_text(text: str) -> str:
    replacements = {'—': '-', '–': '-', '“': '"', '”': '"', '‘': "'", '’': "'", '…': '...', '•': '-', '·': '-'}
    for old_char, new_char in replacements.items():
        text = text.replace(old_char, new_char)
    # Remove tudo q nao for latin-1
    return text.encode("latin-1", "ignore").decode("latin-1")

log = logging.getLogger("seeker.event_map.pdf")

OUTPUT_DIR = os.path.join(os.getcwd(), "data", "event_maps")

class EventMapPDF(FPDF):
    def __init__(self, city_name: str, state_name: str):
        super().__init__()
        self.city_name = city_name
        self.state_name = state_name
        self.set_auto_page_break(auto=True, margin=15)

    def header(self):
        self.set_font("Helvetica", "B", 16)
        self.set_text_color(20, 20, 20)
        self.cell(0, 10, f"Mapa Comercial: {self.city_name} - {self.state_name}", align="C", new_x="LMARGIN", new_y="NEXT")
        
        self.set_font("Helvetica", "I", 9)
        self.set_text_color(100, 100, 100)
        date_str = datetime.now().strftime("%d/%m/%Y")
        self.cell(0, 5, f"Event Map Scout | {date_str} | Inteligencia Preditiva", align="C", new_x="LMARGIN", new_y="NEXT")
        
        self.ln(3)
        self.set_draw_color(200, 200, 200)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, f"Pag. {self.page_no()}/{{nb}}", align="C")

def build_event_map_pdf(report_md: str, cidade: str, estado: str) -> str:
    """Gera um PDF estruturado do mapeamento da cidade."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    safe_city = cidade.replace(" ", "_").replace("/", "").replace("\\", "")
    pdf_path = os.path.join(OUTPUT_DIR, f"Map_{safe_city}_{estado}.pdf")

    try:
        pdf = EventMapPDF(cidade, estado)
        pdf.alias_nb_pages()
        pdf.add_page()
        _render_markdown(pdf, report_md)
        pdf.output(pdf_path)
        return pdf_path
    except Exception as e:
        log.error(f"Erro ao gerar PDF do mapa de {cidade}: {e}")
        return ""

def _render_markdown(pdf: FPDF, md_text: str):
    """Renderizador leve de MD para PDF (customizado)."""
    lines = md_text.split("\n")
    for line in lines:
        stripped = line.strip()
        if not stripped:
            pdf.ln(3)
            continue
            
        if stripped.startswith("## "):
            pdf.set_font("Helvetica", "B", 14)
            pdf.set_text_color(30, 41, 59)
            text = _clean_text(stripped[3:])
            pdf.cell(0, 8, text, new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)
            continue
            
        if stripped.startswith("### "):
            pdf.set_font("Helvetica", "B", 11)
            pdf.set_text_color(50, 50, 50)
            text = _clean_text(stripped[4:])
            pdf.cell(0, 6, text, new_x="LMARGIN", new_y="NEXT")
            continue
            
        # Lists
        if stripped.startswith("- ") or stripped.startswith("* "):
            pdf.set_font("Helvetica", "", 10)
            pdf.set_text_color(60, 60, 60)
            text = _clean_text(_strip_inline_markdown(stripped[2:]))
            try:
                pdf.set_left_margin(15)
                pdf.set_x(15)
                pdf.multi_cell(0, 5, f"- {text}")
            except Exception as e:
                log.warning(f"Ignorando linha de lista no MD erro de pdf: {e}")
            finally:
                pdf.set_left_margin(10)
                pdf.set_x(10)
            continue
            
        # Normal text
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(51, 65, 85)
        text = _clean_text(_strip_inline_markdown(stripped))
        try:
            pdf.multi_cell(0, 5, text)
        except Exception as e:
            log.warning(f"Ignorando linha de texto no MD erro de pdf: {e}")
