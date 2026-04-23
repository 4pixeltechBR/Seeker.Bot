import os
import datetime
from fpdf import FPDF
import logging

log = logging.getLogger("seeker.crm_pdf")

def clean(text: str) -> str:
    if not text: return ""
    return str(text).encode('latin-1', 'replace').decode('latin-1')

def generate_crm_report_pdf(title: str, leads: list[dict]) -> str:
    """Gera um PDF formatado com a lista de leads."""
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    
    # Se a fonte regular existir, você poderia adicioná-la, mas vamos usar Arial Padrão
    pdf.set_font("Arial", "B", 16)
    pdf.cell(0, 10, clean(title), ln=True, align="C")
    pdf.ln(5)
    
    pdf.set_font("Arial", "", 10)
    hoje = datetime.datetime.now().strftime("%d/%m/%Y %H:%M")
    pdf.cell(0, 10, f"Gerado em: {hoje} | Total de Leads: {len(leads)}", ln=True, align="R")
    pdf.ln(5)
    
    for i, lead in enumerate(leads, 1):
        nome = clean(lead.get('nome_evento', 'Desconhecido'))
        cidade = clean(lead.get('cidade', 'GO'))
        score = lead.get('score', 0)
        tipo = clean(lead.get('tipo_evento', 'OUTRO'))
        
        pdf.set_font("Arial", "B", 12)
        pdf.set_fill_color(240, 240, 240)
        pdf.cell(0, 10, f"{i}. {nome} - {cidade} [Score: {score}]", ln=True, fill=True)
        
        pdf.set_font("Arial", "", 10)
        
        fields = [
            ("Tipo Evento", tipo),
            ("Período", clean(lead.get("periodo", "N/A"))),
            ("Porte / Orçamento", f"{clean(lead.get('porte_estimado', 'N/A'))} / {clean(lead.get('orcamento_estimado', 'N/A'))}"),
            ("Contratante", clean(lead.get("tipo_contratante", "N/A"))),
            ("Decisor", f"{clean(lead.get('decisor_nome', 'N/A'))} ({clean(lead.get('decisor_cargo', ''))})"),
            ("WhatsApp", clean(lead.get("whatsapp", "N/A"))),
            ("Instagram", clean(lead.get("instagram", "N/A"))),
        ]
        
        for label, val in fields:
            pdf.set_font("Arial", "B", 10)
            start_y = pdf.get_y()
            pdf.set_xy(pdf.l_margin, start_y)
            pdf.cell(40, 6, label + ":", border=0)
            pdf.set_font("Arial", "", 10)
            pdf.set_xy(pdf.l_margin + 40, start_y)
            val_str = clean(str(val) if val else "N/A")
            pdf.multi_cell(0, 6, val_str)
            
        pdf.set_xy(pdf.l_margin, pdf.get_y())
        pdf.ln(5)
        
    out_dir = os.path.join(os.getcwd(), "data", "reports")
    os.makedirs(out_dir, exist_ok=True)
    safe_title = title.replace(" ", "_").replace("/", "-").lower()
    file_path = os.path.join(out_dir, f"CRM_Report_{safe_title}_{int(datetime.datetime.now().timestamp())}.pdf")
    
    pdf.output(file_path)
    return file_path
