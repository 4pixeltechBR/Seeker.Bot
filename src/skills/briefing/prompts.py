"""
Seeker.Bot — Briefing Goal
src/skills/briefing/prompts.py
"""

BRIEFING_PROMPT = """
Sua tarefa é analisar os seguintes e-mails NÃO LIDOS extraídos da caixa de entrada do usuário via IMAP e gerar um resumo passivo diário, estilo "Overview Matinal".

Foque com prioridade em e-mails que tragam novidades de tecnologia, lançamentos de modelos de IA, frameworks, newsletters de mercado (como AiDrop, Deschamps, etc.) e atualizações de produtos.

FORMATO DE SAÍDA EXIGIDO (Telegram HTML):
<b>☀️ Briefing Matinal Seeker — E-mails</b>

<i>Você tem {total_emails} e-mails novos.</i>

<b>📧 Resumo dos E-mails:</b>
(Gere um resumo estruturado em bullet points dos emails recebidos. Agrupe por remetente ou tema, focando no assunto e conteúdo principal. Destaque novidades de IA e tecnologia primeiro.)

REGRAS CRÍTICAS DE FORMATAÇÃO E SEGURANÇA:
- Seja direto e objetivo.
- Use APENAS as tags HTML <b> e <i> para formatação de texto.
- NUNCA use a tag de link <a> ou <a> com mailto. Se precisar mencionar um e-mail ou link de site, escreva-o em formato puramente textual (ex: waldemar@techleads.club ou aidrop.news). O Telegram já converte links textuais em clicáveis de forma nativa e isso evita quebras de tags escapadas.
- Se o campo "body" contiver lixo de formatação HTML cru, ignore a formatação e extraia apenas a essência textual.

--- EMAILS RECEBIDOS ---
{emails_context}
"""
