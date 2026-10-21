"""Ferramentas de e-mail. Ler é livre. O resto espera autorização."""

from __future__ import annotations

from seeker.skills.contract import Skill


def read_mail_skill(box) -> Skill:
    def run(arguments: dict) -> str:
        try:
            limit = int(arguments.get("limit") or 8)
        except (TypeError, ValueError):
            limit = 8
        try:
            return box.unseen(limit)
        except Exception:
            return "Não consegui ler a caixa."

    return Skill(
        name="read_mail",
        when="Lê os e-mails novos da caixa. Use quando a pessoa perguntar o que chegou ou pedir para ver a caixa.",
        risk="leitura",
        needs_approval=False,
        parameters={
            "type": "object",
            "properties": {"limit": {"type": "integer", "description": "Quantos e-mails, no máximo 15."}},
        },
        run=run,
    )


def write_mail_skill(box) -> Skill:
    def run(arguments: dict) -> str:
        try:
            return box.draft(str(arguments.get("to") or ""), str(arguments.get("subject") or ""), str(arguments.get("body") or ""))
        except Exception as exc:
            return str(exc)

    return _letter_skill(
        "write_mail",
        "Salva um rascunho na caixa, sem enviar. Use quando a pessoa pedir para escrever um e-mail.",
        run,
    )


def send_mail_skill(box) -> Skill:
    def run(arguments: dict) -> str:
        try:
            return box.send(str(arguments.get("to") or ""), str(arguments.get("subject") or ""), str(arguments.get("body") or ""))
        except Exception as exc:
            return str(exc)

    return _letter_skill(
        "send_mail",
        "Envia um e-mail de verdade. Use só depois que a pessoa autorizar o texto e o destinatário.",
        run,
    )


def delete_mail_skill(box) -> Skill:
    def run(arguments: dict) -> str:
        try:
            return box.delete(str(arguments.get("uid") or ""))
        except Exception:
            return "Não consegui apagar o e-mail."

    return Skill(
        name="delete_mail",
        when="Apaga um e-mail da caixa pelo número. Use só quando a pessoa pedir para excluir aquele número.",
        risk="altera",
        needs_approval=True,
        parameters={
            "type": "object",
            "properties": {"uid": {"type": "string", "description": "Número do e-mail mostrado na leitura."}},
            "required": ["uid"],
        },
        run=run,
    )


def _letter_skill(name: str, when: str, run) -> Skill:
    return Skill(
        name=name,
        when=when,
        risk="altera",
        needs_approval=True,
        parameters={
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Destinatário."},
                "subject": {"type": "string", "description": "Assunto."},
                "body": {"type": "string", "description": "Texto da mensagem."},
            },
            "required": ["to", "subject", "body"],
        },
        run=run,
    )
