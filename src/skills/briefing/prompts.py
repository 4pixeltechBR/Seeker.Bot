"""
Seeker.Bot — Briefing Goal
src/skills/briefing/prompts.py
"""

BRIEFING_PROMPT = """
Sua tarefa é analisar os seguintes e-mails NÃO LIDOS extraídos da caixa de entrada do usuário via IMAP e gerar um resumo passivo diário, estilo "Overview Matinal".

Foque ESPECIFICAMENTE em identificar e destacar "decisores" (profissionais em cargos de liderança, diretores, tomadores de decisão ou contatos corporativos importantes) e seus contatos (e-mail, assinatura).

FORMATO DE SAÍDA EXIGIDO (Telegram HTML):
<b>☀️ Briefing Matinal Seeker — E-mails</b>

<i>Você tem {total_emails} e-mails novos.</i>

<b>🚨 Decisores e Contatos Identificados:</b>
(Liste aqui quem são os decisores encontrados nos emails. Inclua Nome, Cargo [se possível inferir], Empresa e E-mail de forma concisa. Se nenhum for encontrado, diga "Nenhum decisor óbvio detectado hoje.")

<b>📧 Resumo dos E-mails:</b>
(Gere um resumo em bullet points dos emails recebidos. Agrupe por remetente ou tema, focando no assunto e conteúdo principal.)

REGRAS:
- Seja ultra direto.
- Se o campo "body" conter lixo de formatação HTML cru, ignore a formatação e extraia a essência.
- O seu output OBRIGATORIAMENTE deve ser seguro para envio via HTML no Telegram (use apenas <b>, <i>, <a>, <u>, <s> e evite tags complexas).

--- EMAILS RECEBIDOS ---
{emails_context}
"""
