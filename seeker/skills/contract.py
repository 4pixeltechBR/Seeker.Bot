"""Contrato de uma skill: o modelo só vê o que tem nome, regra e função."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


class SkillError(Exception):
    pass


@dataclass(frozen=True)
class Skill:
    name: str
    when: str
    risk: str
    needs_approval: bool
    parameters: dict
    run: Callable[[dict], str]

    def spec(self) -> dict:
        return {
            "name": self.name,
            "description": self.when,
            "parameters": self.parameters,
        }


class Catalog:
    def __init__(self):
        self._skills: dict[str, Skill] = {}

    def add(self, skill: Skill) -> None:
        if not skill.name.isidentifier():
            raise SkillError("O nome da skill precisa ser um identificador.")
        if len(skill.when.strip()) < 20:
            raise SkillError(f"{skill.name} não diz quando usar.")
        if skill.risk not in {"leitura", "altera"}:
            raise SkillError(f"{skill.name} precisa declarar o risco.")
        if not isinstance(skill.needs_approval, bool):
            raise SkillError(f"{skill.name} precisa declarar a aprovação.")
        if skill.risk == "altera" and not skill.needs_approval:
            raise SkillError(f"{skill.name} altera o computador e precisa de aprovação.")
        if not isinstance(skill.parameters, dict):
            raise SkillError(f"{skill.name} está sem parâmetros.")
        if not callable(skill.run):
            raise SkillError(f"{skill.name} está sem função.")
        if skill.name in self._skills:
            raise SkillError(f"{skill.name} já existe.")
        self._skills[skill.name] = skill

    def has(self, name: str) -> bool:
        return name in self._skills

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def drop_prefix(self, prefix: str) -> None:
        self._skills = {name: skill for name, skill in self._skills.items() if not name.startswith(prefix)}

    def specs(self) -> list[dict]:
        return [skill.spec() for skill in self._skills.values()]

    def run(self, name: str, arguments: dict) -> str:
        skill = self._skills.get(name)
        if skill is None:
            return "Ferramenta desconhecida."
        if not isinstance(arguments, dict):
            return "Não consegui ler os argumentos."
        return skill.run(arguments)

    def notes(self) -> str:
        if not self._skills:
            return ""
        lines = [f"- {skill.name}: {skill.when}" for skill in self._skills.values()]
        return "Skills:\n" + "\n".join(lines)
