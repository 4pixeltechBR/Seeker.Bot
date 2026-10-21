"""Cria uma ferramenta nova só depois da autorização. O teste precisa passar."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

from seeker.skills.contract import Catalog, Skill, SkillError

CREATE_NO_WINDOW = 0x08000000
RESERVED = {
    "create_skill",
    "gpu_memory",
    "research",
    "read_page",
    "read_feed",
    "last30days",
    "read_mail",
    "write_mail",
    "send_mail",
    "delete_mail",
    "submit_form",
    "configure_mcp",
    "request_secret",
    "run_command",
    "agent",
    "runtime",
    "contract",
    "catalog",
}
SOURCE_CAP = 12000
TEST_CAP = 8000


def create_skill_tool(catalog: Catalog, root: Path, check=None) -> Skill:
    def run(arguments: dict) -> str:
        try:
            return install(
                root,
                catalog,
                name=str(arguments.get("name") or ""),
                when=str(arguments.get("when") or ""),
                risk=str(arguments.get("risk") or ""),
                source=str(arguments.get("source") or ""),
                test=str(arguments.get("test") or ""),
                check=check,
            )
        except SkillError as exc:
            return str(exc)

    return Skill(
        name="create_skill",
        when=(
            "Cria uma ferramenta nova quando falta um jeito de resolver o pedido. "
            "Use com o módulo Python, o teste e o risco. Sempre espera autorização antes de gravar."
        ),
        risk="altera",
        needs_approval=True,
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Identificador da ferramenta, em inglês."},
                "when": {"type": "string", "description": "Quando usar, com pelo menos 20 caracteres."},
                "risk": {"type": "string", "description": "leitura ou altera."},
                "source": {
                    "type": "string",
                    "description": "Módulo Python com def build() devolvendo Skill. O name de dentro tem de bater.",
                },
                "test": {"type": "string", "description": "Teste pytest com def test_."},
            },
            "required": ["name", "when", "risk", "source", "test"],
        },
        run=run,
    )


def install(
    root: Path,
    catalog: Catalog,
    name: str,
    when: str,
    risk: str,
    source: str,
    test: str,
    check=None,
) -> str:
    name = name.strip()
    when = when.strip()
    risk = risk.strip()
    _check_proposal(catalog, name, when, risk, source, test)
    folder = root / "seeker" / "skills" / "custom"
    tests = root / "tests"
    folder.mkdir(parents=True, exist_ok=True)
    tests.mkdir(parents=True, exist_ok=True)
    init = folder / "__init__.py"
    if not init.exists():
        init.write_text('"""Ferramentas criadas pelo Seeker, depois do sim."""\n', encoding="utf-8")
    source_path = folder / f"{name}.py"
    test_path = tests / f"test_custom_{name}.py"
    if source_path.exists() or test_path.exists():
        raise SkillError(f"{name} já existe.")
    source_path.write_text(source, encoding="utf-8")
    test_path.write_text(test, encoding="utf-8")
    try:
        skill = load_skill(source_path)
        if skill.name != name or skill.when.strip() != when or skill.risk != risk:
            raise SkillError("O build() não bate com o nome, o quando usar ou o risco.")
        probe = Catalog()
        probe.add(skill)
        (check or pytest_check)(root, test_path)
        catalog.add(load_skill(source_path))
    except Exception as exc:
        source_path.unlink(missing_ok=True)
        test_path.unlink(missing_ok=True)
        if isinstance(exc, SkillError):
            raise
        raise SkillError(str(exc)) from exc
    return f"Criei a ferramenta {name}. Já pode usar."


def load_custom(catalog: Catalog, root: Path) -> list[str]:
    folder = root / "seeker" / "skills" / "custom"
    if not folder.exists():
        return []
    problems = []
    for path in sorted(folder.glob("*.py")):
        if path.name.startswith("_"):
            continue
        try:
            skill = load_skill(path)
            if skill.name != path.stem or skill.name in RESERVED or catalog.has(skill.name):
                raise SkillError(f"{path.name} não entra no catálogo.")
            catalog.add(skill)
        except (SkillError, OSError, SyntaxError) as exc:
            problems.append(f"{path.name}: {exc}")
    return problems


def load_skill(path: Path) -> Skill:
    module_name = f"seeker.skills.custom.{path.stem}"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise SkillError(f"Não li {path.name}.")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    build = getattr(module, "build", None)
    if not callable(build):
        raise SkillError("O módulo precisa definir build().")
    skill = build()
    if not isinstance(skill, Skill):
        raise SkillError("build() precisa devolver uma Skill.")
    return skill


def pytest_check(root: Path, test_path: Path) -> None:
    python = root / ".venv" / "Scripts" / "python.exe"
    if not python.exists():
        python = Path(sys.executable)
    completed = subprocess.run(
        [str(python), "-m", "pytest", str(test_path), "-q", "--tb=line"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=60,
        encoding="utf-8",
        errors="replace",
        creationflags=CREATE_NO_WINDOW,
    )
    if completed.returncode != 0:
        detail = ((completed.stdout or "") + (completed.stderr or "")).strip()
        raise SkillError(detail[-1500:] or "O teste falhou.")


def _check_proposal(catalog: Catalog, name: str, when: str, risk: str, source: str, test: str) -> None:
    if not name.isidentifier() or name in RESERVED or catalog.has(name):
        raise SkillError("Esse nome não pode ser uma ferramenta nova.")
    if len(when) < 20:
        raise SkillError("Diga quando usar, com pelo menos 20 caracteres.")
    if risk not in {"leitura", "altera"}:
        raise SkillError("O risco é leitura ou altera.")
    if "def build" not in source:
        raise SkillError("O módulo precisa definir build().")
    if "def test_" not in test:
        raise SkillError("O teste precisa ter def test_.")
    if len(source) > SOURCE_CAP or len(test) > TEST_CAP:
        raise SkillError("O código passou do tamanho.")
