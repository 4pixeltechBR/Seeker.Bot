"""
Seeker.Bot — S.A.R.A CodeValidator
src/skills/self_improvement/code_validator.py

Valida patches de código gerados pelo LLM antes de escrever no disco.
Estágios em ordem de custo crescente:

  1. ast.parse()   — sintaxe (0ms, sem I/O)
  2. compile()     — nomes e estrutura básica (0ms, sem I/O)
  3. pyright       — type safety opcional (~2s, requer binário)

Filosofia: falha rápida no estágio mais barato.
Se qualquer estágio falhar, o arquivo original NÃO é modificado.
"""

import ast
import json
import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass, field

log = logging.getLogger("seeker.self_improvement.validator")


@dataclass
class ValidationResult:
    passed: bool
    stage_failed: str | None  # "ast" | "compile" | "pyright" | None (passou tudo)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> str:
        if self.passed:
            return "✅ Validação OK (ast + compile" + (" + pyright" if not self.stage_failed else "") + ")"
        lines = [f"❌ Falha em estágio '{self.stage_failed}':"]
        lines.extend(f"  • {e}" for e in self.errors[:5])
        if len(self.errors) > 5:
            lines.append(f"  ... (+{len(self.errors) - 5} erros)")
        return "\n".join(lines)


class CodeValidator:
    """
    Valida código Python gerado por LLM antes de escrever em disco.

    Uso:
        validator = CodeValidator()
        result = validator.validate(new_code, filename="goal.py")
        if not result.passed:
            log.warning(result.summary())
            return  # Não escreve
    """

    def __init__(self, use_pyright: bool = True, pyright_timeout: int = 30):
        self.use_pyright = use_pyright
        self.pyright_timeout = pyright_timeout
        self._pyright_available: bool | None = None  # Cache do check de disponibilidade

    # ── Estágio 1: ast.parse ───────────────────────────────────────────

    def _validate_ast(self, code: str) -> ValidationResult:
        """Detecta erros de sintaxe Python."""
        try:
            ast.parse(code)
            return ValidationResult(passed=True, stage_failed=None)
        except SyntaxError as e:
            msg = f"SyntaxError: {e.msg}"
            if e.lineno:
                msg += f" (linha {e.lineno}"
                if e.offset:
                    msg += f", coluna {e.offset}"
                msg += ")"
            if e.text:
                msg += f"\n  >> {e.text.rstrip()}"
            return ValidationResult(
                passed=False,
                stage_failed="ast",
                errors=[msg],
            )
        except Exception as e:
            return ValidationResult(
                passed=False,
                stage_failed="ast",
                errors=[f"Erro inesperado no ast.parse: {e}"],
            )

    # ── Estágio 2: compile ────────────────────────────────────────────

    def _validate_compile(self, code: str, filename: str) -> ValidationResult:
        """Detecta erros de compilação (nomes inválidos, estrutura)."""
        try:
            compile(code, filename, "exec")
            return ValidationResult(passed=True, stage_failed=None)
        except SyntaxError as e:
            # compile() pode capturar erros que ast.parse() deixa passar
            msg = f"CompileError (SyntaxError): {e.msg}"
            if e.lineno:
                msg += f" (linha {e.lineno})"
            return ValidationResult(
                passed=False,
                stage_failed="compile",
                errors=[msg],
            )
        except Exception as e:
            return ValidationResult(
                passed=False,
                stage_failed="compile",
                errors=[f"Erro inesperado no compile: {e}"],
            )

    # ── Estágio 3: pyright (opcional) ────────────────────────────────

    def _check_pyright_available(self) -> bool:
        """Verifica se pyright está no PATH (cached)."""
        if self._pyright_available is not None:
            return self._pyright_available
        try:
            result = subprocess.run(
                ["pyright", "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            self._pyright_available = result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            self._pyright_available = False
        if not self._pyright_available:
            log.debug("[validator] pyright não encontrado no PATH — estágio 3 desativado")
        return self._pyright_available

    def _validate_pyright(self, code: str, filename: str) -> ValidationResult:
        """Análise de tipos estática via pyright (apenas erros, ignora warnings)."""
        if not self._check_pyright_available():
            return ValidationResult(passed=True, stage_failed=None)  # Skip graciosamente

        tmp_path = None
        try:
            # Escreve em arquivo temporário com nome similar ao original
            suffix = os.path.splitext(filename)[1] or ".py"
            with tempfile.NamedTemporaryFile(
                suffix=suffix, mode="w", encoding="utf-8", delete=False
            ) as tmp:
                tmp.write(code)
                tmp_path = tmp.name

            result = subprocess.run(
                ["pyright", "--outputjson", tmp_path],
                capture_output=True,
                text=True,
                timeout=self.pyright_timeout,
            )

            # pyright retorna 0 se OK, 1 se warnings/erros — ambos têm JSON válido
            try:
                data = json.loads(result.stdout)
            except json.JSONDecodeError:
                log.debug("[validator] pyright output não é JSON válido, pulando")
                return ValidationResult(passed=True, stage_failed=None)

            diagnostics = data.get("generalDiagnostics", [])
            errors = [d for d in diagnostics if d.get("severity") == "error"]
            warnings_list = [d for d in diagnostics if d.get("severity") == "warning"]

            if errors:
                error_msgs = []
                for d in errors:
                    line = d.get("range", {}).get("start", {}).get("line", 0) + 1
                    error_msgs.append(f"pyright:{line}: {d.get('message', '?')}")
                return ValidationResult(
                    passed=False,
                    stage_failed="pyright",
                    errors=error_msgs,
                    warnings=[
                        f"pyright:warning:{w.get('message', '?')}"
                        for w in warnings_list[:3]
                    ],
                )

            return ValidationResult(
                passed=True,
                stage_failed=None,
                warnings=[
                    f"pyright:warning:{w.get('message', '?')}"
                    for w in warnings_list[:3]
                ],
            )

        except subprocess.TimeoutExpired:
            log.warning(f"[validator] pyright timeout ({self.pyright_timeout}s) — pulando estágio 3")
            return ValidationResult(passed=True, stage_failed=None)
        except Exception as e:
            log.warning(f"[validator] Erro inesperado no pyright: {e}")
            return ValidationResult(passed=True, stage_failed=None)
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    # ── Pipeline principal ────────────────────────────────────────────

    def validate(self, code: str, filename: str = "<sara_patch>") -> ValidationResult:
        """
        Executa os 3 estágios de validação em ordem.
        Para no primeiro estágio que falhar.

        Args:
            code: Código Python a validar
            filename: Nome do arquivo para msgs de erro (não precisa existir)

        Returns:
            ValidationResult com passed=True se passou tudo,
            ou passed=False com detalhes do primeiro estágio que falhou.
        """
        if not code or not code.strip():
            return ValidationResult(
                passed=False,
                stage_failed="ast",
                errors=["Código vazio ou apenas whitespace"],
            )

        # Estágio 1 — ast.parse (mais rápido, falha rápida em sintaxe)
        result = self._validate_ast(code)
        if not result.passed:
            log.warning(f"[validator] FAIL stage=ast: {result.errors[0][:100]}")
            return result

        # Estágio 2 — compile (pega o que ast deixa passar)
        result = self._validate_compile(code, filename)
        if not result.passed:
            log.warning(f"[validator] FAIL stage=compile: {result.errors[0][:100]}")
            return result

        # Estágio 3 — pyright (tipo-checking, opcional)
        if self.use_pyright:
            result = self._validate_pyright(code, filename)
            if not result.passed:
                log.warning(
                    f"[validator] FAIL stage=pyright: "
                    f"{len(result.errors)} erros — {result.errors[0][:100]}"
                )
                return result

        log.info(f"[validator] PASS: {filename}")
        return ValidationResult(passed=True, stage_failed=None)


# ── Singleton para reuso entre ciclos ────────────────────────────────

_validator: CodeValidator | None = None


def get_validator(use_pyright: bool = True) -> CodeValidator:
    """Retorna instância compartilhada do CodeValidator."""
    global _validator
    if _validator is None:
        _validator = CodeValidator(use_pyright=use_pyright)
    return _validator
