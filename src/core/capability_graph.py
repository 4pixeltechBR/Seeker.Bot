"""
Seeker.Bot — Capability Graph

src/core/capability_graph.py

Grafo dirigido de habilidades (capabilities) para planejamento e descoberta
de skills. Cada skill registra:
  - capabilities: ações que pode executar (ex: "search_web", "send_email")
  - dependencies: capabilities de que precisa (ex: "fetch_credentials")

Permite:
  - Descobrir qual skill provem uma capability
  - Resolver planos simples em ordem topológica
  - Detectar dependências faltantes
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger("seeker.capability_graph")


@dataclass
class CapabilityNode:
    skill: str
    capabilities: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)


class CapabilityGraph:
    """In-memory capability graph with dependency resolution."""

    def __init__(self):
        self._nodes: dict[str, CapabilityNode] = {}
        self._capability_to_skill: dict[str, str] = {}

    def register(
        self,
        skill: str,
        capabilities: list[str],
        dependencies: list[str] | None = None,
    ) -> None:
        """Register or update a skill in the graph."""
        dependencies = dependencies or []
        node = CapabilityNode(
            skill=skill,
            capabilities=list(capabilities),
            dependencies=list(dependencies),
        )
        self._nodes[skill] = node
        for cap in capabilities:
            if cap in self._capability_to_skill and self._capability_to_skill[cap] != skill:
                log.warning(
                    f"[capability] Conflito: '{cap}' já registrado por "
                    f"'{self._capability_to_skill[cap]}' e agora por '{skill}'"
                )
            self._capability_to_skill[cap] = skill
        log.debug(f"[capability] Registrado {skill}: {capabilities}")

    def find_provider(self, capability: str) -> Optional[str]:
        """Return skill that provides a capability, if any."""
        return self._capability_to_skill.get(capability)

    def resolve(self, target_capabilities: list[str]) -> list[str]:
        """
        Resolve execution order for a list of target capabilities.
        Returns skill names in topological order (dependencies first).
        Raises RuntimeError if a capability is missing or cycle detected.
        """
        plan: list[str] = []
        visited: set[str] = set()
        temp: set[str] = set()

        def visit(cap: str) -> None:
            skill = self._capability_to_skill.get(cap)
            if skill is None:
                raise RuntimeError(f"Capability não registrada: {cap}")
            if skill in temp:
                raise RuntimeError(f"Ciclo de dependências detectado em {skill}")
            if skill in visited:
                return

            temp.add(skill)
            node = self._nodes[skill]
            for dep_cap in node.dependencies:
                visit(dep_cap)
            temp.remove(skill)
            visited.add(skill)
            plan.append(skill)

        for cap in target_capabilities:
            visit(cap)
        return plan

    def list_capabilities(self) -> list[str]:
        return sorted(self._capability_to_skill.keys())

    def list_skills(self) -> list[str]:
        return sorted(self._nodes.keys())


# Singleton global
_graph: CapabilityGraph | None = None


def get_capability_graph() -> CapabilityGraph:
    global _graph
    if _graph is None:
        _graph = CapabilityGraph()
    return _graph
