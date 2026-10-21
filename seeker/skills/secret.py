"""Pede o cartão do cofre. A função não recebe e não devolve o valor."""

from __future__ import annotations

from seeker.secrets import NAMES, known_name, label_for
from seeker.skills.contract import Skill


def request_secret_skill() -> Skill:
    def run(arguments: dict) -> str:
        name = known_name(str(arguments.get("name") or ""))
        if not name:
            return "Diga qual chave: Gemini, Maritaca, NVIDIA, Groq, e-mail ou Telegram. Não cole o valor."
        return f"O cartão da chave {label_for(name)} abre no cofre. O valor não entra aqui."

    return Skill(
        name="request_secret",
        when=(
            "Abre o cofre seguro para a pessoa digitar uma chave. "
            "Use quando pedirem para guardar, trocar ou informar chave, token ou senha de API. "
            "Não peça o valor no chat."
        ),
        risk="leitura",
        needs_approval=False,
        parameters={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "enum": list(NAMES),
                    "description": "Nome da chave. Nunca envie o valor.",
                }
            },
            "required": ["name"],
        },
        run=run,
    )
