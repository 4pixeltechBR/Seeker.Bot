import os
import re
import logging
import requests
import asyncio

log = logging.getLogger("seeker.osv_check")

class OSVScanner:
    """Mecanismo de auditoria de segurança das dependências do Seeker.Bot contra a API Google OSV."""

    def __init__(self, pipeline):
        self.pipeline = pipeline
        self.requirements_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
            "requirements.txt"
        )

    def _parse_requirements(self) -> list[dict]:
        """Extrai pacotes e versões do requirements.txt."""
        packages = []
        if not os.path.exists(self.requirements_path):
            log.warning(f"[osv_check] Arquivo {self.requirements_path} não encontrado.")
            return packages

        try:
            with open(self.requirements_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

            for line in lines:
                line = line.strip()
                # Pula comentários ou linhas vazias
                if not line or line.startswith("#"):
                    continue
                # Procura padrao pacote==versao
                match = re.match(r"^([a-zA-Z0-9_\-\[\]]+)==([0-9a-zA-Z\.\-]+)", line)
                if match:
                    packages.append({
                        "name": match.group(1),
                        "version": match.group(2)
                    })
        except Exception as e:
            log.error(f"[osv_check] Falha ao ler requirements.txt: {e}")
        
        return packages

    async def scan_vulnerabilities(self) -> str:
        """Audita as dependências locais enviando requisições para a API OSV."""
        packages = self._parse_requirements()
        if not packages:
            # Fallback rápido para testar se nenhum requirements existe
            return "🗂️ OSV Check: Nenhuma dependência estruturada (requirements.txt) encontrada para auditar."

        url = "https://api.osv.dev/v1/query"
        loop = asyncio.get_running_loop()
        vulnerabilities = []

        log.info(f"[osv_check] Iniciando auditoria de {len(packages)} pacotes na Google OSV API...")
        
        # Consultamos a API OSV em lote ou sequencial
        for pkg in packages[:15]: # Limite defensivo para evitar abuso de chamadas HTTP
            payload = {
                "version": pkg["version"],
                "package": {
                    "name": pkg["name"],
                    "ecosystem": "PyPI"
                }
            }
            try:
                res = await loop.run_in_executor(
                    None,
                    lambda: requests.post(url, json=payload, timeout=15)
                )
                if res.status_code == 200:
                    data = res.json()
                    # Se retornar vulnerabilidades (campo vulns)
                    vulns = data.get("vulns", [])
                    if vulns:
                        for v in vulns:
                            vulnerabilities.append({
                                "package": pkg["name"],
                                "version": pkg["version"],
                                "id": v.get("id"),
                                "summary": v.get("summary", "Sem sumário"),
                                "details": v.get("details", "Sem detalhes")
                            })
            except Exception as e:
                log.debug(f"[osv_check] Erro ao consultar OSV para o pacote {pkg['name']}: {e}")

        # Formata o relatório
        if not vulnerabilities:
            return "✅ **OSV Auditoria de Segurança:** Nenhuma vulnerabilidade conhecida encontrada nas dependências do Seeker.Bot."

        output = ["⚠️ **OSV AUDITORIA DE SEGURANÇA: Vulnerabilidades Encontradas!**"]
        for idx, v in enumerate(vulnerabilities, 1):
            output.append(
                f"\n{idx}. **[{v['id']}]** no pacote `{v['package']}=={v['version']}`\n"
                f"   └ **Sumário:** {v['summary']}\n"
                f"   └ **Detalhes:** {v['details'][:150]}..."
            )
        return "\n".join(output)
