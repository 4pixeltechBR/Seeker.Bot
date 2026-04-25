"""
Seeker.Bot — Goal Registry
src/core/goals/registry.py

Auto-discovery de goals por convenção de pasta.

Convenção:
    src/skills/{nome_do_goal}/goal.py deve expor:
        def create_goal(pipeline: SeekerPipeline) -> AutonomousGoal

    Exemplo:
        src/skills/revenue_hunter/goal.py
        src/skills/sense_news/goal.py
        src/skills/briefing/goal.py

    Se o módulo não tiver create_goal(), é ignorado silenciosamente.
    Se o import falhar (dep faltando), loga erro e continua.
    Se o goal estiver na deny_list, pula.

Filosofia: explícito > mágico. O registry descobre, mas cada goal
decide se existe via factory function. Sem metaclasses, sem decorators,
sem __init_subclass__. Um import e uma chamada.
"""

import importlib
import logging
import os
from pathlib import Path

from src.core.goals.protocol import AutonomousGoal

log = logging.getLogger("seeker.registry")

SKILLS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "skills",
)

CONFIG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "config",
)


def _load_skills_deny_list() -> set[str]:
    """
    Lê config/skills.yaml e retorna set de skills desabilitadas.
    Se o arquivo não existir, retorna set vazio (carrega tudo).
    """
    skills_yaml = os.path.join(CONFIG_DIR, "skills.yaml")
    if not os.path.exists(skills_yaml):
        return set()

    try:
        import yaml
        with open(skills_yaml, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}

        disabled: set[str] = set()
        for category in ("core", "recommended", "specialist"):
            section = config.get(category, {})
            if isinstance(section, dict):
                for skill_name, enabled in section.items():
                    if not enabled:
                        disabled.add(skill_name)

        if disabled:
            log.info(f"[registry] skills.yaml: {len(disabled)} skills desabilitadas: {disabled}")
        return disabled

    except ImportError:
        log.warning("[registry] PyYAML não instalado — ignorando skills.yaml")
        return set()
    except Exception as e:
        log.warning(f"[registry] Erro ao ler skills.yaml: {e} — carregando todas as skills")
        return set()


def discover_goals(
    pipeline,
    deny_list: set[str] | None = None,
    skills_dir: str | None = None,
) -> list[AutonomousGoal]:
    """
    Escaneia src/skills/*/goal.py procurando create_goal(pipeline).
    
    Args:
        pipeline: SeekerPipeline (passado pra cada factory)
        deny_list: nomes de goals a ignorar (ex: {"revenue_hunter"})
        skills_dir: override do diretório de skills (pra testes)
    
    Returns:
        Lista de goals instanciados e prontos pro scheduler.
    """
    deny_list = deny_list or set()
    # Merge: deny_list do parâmetro + deny_list do skills.yaml
    yaml_deny = _load_skills_deny_list()
    deny_list = deny_list | yaml_deny
    base_dir = Path(skills_dir or SKILLS_DIR)

    if not base_dir.exists():
        log.warning(f"[registry] Diretório de skills não encontrado: {base_dir}")
        return []

    goals: list[AutonomousGoal] = []
    discovered = 0
    skipped = 0
    failed = 0

    for skill_dir in sorted(base_dir.iterdir()):
        # Só diretórios com goal.py
        goal_file = skill_dir / "goal.py"
        if not skill_dir.is_dir() or not goal_file.exists():
            continue

        discovered += 1
        skill_name = skill_dir.name

        # Deny list check (antes do import — não gasta tempo)
        if skill_name in deny_list:
            log.info(f"[registry] ⏭ {skill_name} — na deny-list, ignorado.")
            skipped += 1
            continue

        # Import dinâmico
        module_path = f"src.skills.{skill_name}.goal"
        try:
            module = importlib.import_module(module_path)
        except Exception as e:
            log.error(
                f"[registry] ❌ {skill_name} — falha no import: {e}. "
                f"Dependência faltando? Continuando sem."
            )
            failed += 1
            continue

        # Factory function
        factory = getattr(module, "create_goal", None)
        if factory is None:
            log.debug(
                f"[registry] {skill_name}/goal.py não tem create_goal(), "
                f"ignorado (pode ser skill não-autônoma)."
            )
            continue

        # Instanciação
        try:
            goal = factory(pipeline)

            # Valida que implementa o protocol
            if not isinstance(goal, AutonomousGoal):
                log.error(
                    f"[registry] ❌ {skill_name} — create_goal() retornou "
                    f"{type(goal).__name__}, não implementa AutonomousGoal."
                )
                failed += 1
                continue

            # Double-check deny list pelo name do goal (pode diferir do nome da pasta)
            if goal.name in deny_list:
                log.info(f"[registry] ⏭ {goal.name} — na deny-list, ignorado.")
                skipped += 1
                continue

            goals.append(goal)
            log.info(f"[registry] ✅ {goal.name} — registrado ({module_path})")

        except Exception as e:
            log.error(
                f"[registry] ❌ {skill_name} — create_goal() falhou: {e}. "
                f"Continuando sem."
            )
            failed += 1

    log.info(
        f"[registry] Discovery completo: "
        f"{len(goals)} ativos, {skipped} na deny-list, "
        f"{failed} falharam, {discovered} encontrados."
    )

    return goals
