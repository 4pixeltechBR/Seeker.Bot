#!/usr/bin/env python3
"""
Configure GitHub repository automatically using the GitHub API.

Requer: pip install requests

Usage:
    python scripts/setup_github_repo.py <github_token> <owner> <repo>

Exemplo:
    python scripts/setup_github_repo.py ghp_xxxxxxxxxxxx 4pixeltechBR Seeker.Bot

Para gerar um token:
    1. Vá para https://github.com/settings/tokens
    2. Clique "Generate new token (classic)"
    3. Selecione scopes: repo, admin:repo_hook, admin:org_hook
    4. Copie o token e execute este script
"""

import sys
import json
import requests
from typing import Optional

class GitHubRepoConfigurer:
    def __init__(self, token: str, owner: str, repo: str):
        self.token = token
        self.owner = owner
        self.repo = repo
        self.base_url = f"https://api.github.com/repos/{owner}/{repo}"
        self.headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
            "X-GitHub-Api-Version": "2022-11-28"
        }

    def _request(self, method: str, endpoint: str, data: Optional[dict] = None) -> dict:
        """Make API request."""
        url = f"{self.base_url}{endpoint}"
        try:
            if method == "GET":
                resp = requests.get(url, headers=self.headers)
            elif method == "PUT":
                resp = requests.put(url, headers=self.headers, json=data)
            elif method == "PATCH":
                resp = requests.patch(url, headers=self.headers, json=data)
            else:
                raise ValueError(f"Unknown method: {method}")

            resp.raise_for_status()
            return resp.json() if resp.text else {}
        except requests.exceptions.RequestException as e:
            print(f"❌ Erro na requisição: {e}")
            return {}

    def enable_features(self) -> bool:
        """Enable Discussions, Issues, Projects."""
        print("\n🔧 Ativando features...")
        data = {
            "has_discussions": True,
            "has_issues": True,
            "has_projects": True
        }
        result = self._request("PATCH", "", data)
        if result:
            print("✅ Features ativadas")
            return True
        return False

    def protect_main_branch(self) -> bool:
        """Protect main branch with status checks."""
        print("\n🛡️ Protegendo branch main...")
        data = {
            "required_status_checks": {
                "strict": True,
                "contexts": ["tests"]
            },
            "required_pull_request_reviews": {
                "dismiss_stale_reviews": True,
                "require_code_owner_reviews": False
            },
            "enforce_admins": True,
            "required_linear_history": False,
            "restrictions": None
        }
        result = self._request("PUT", "/branches/main/protection", data)
        if result:
            print("✅ Branch main protegido (requer PR + testes passando)")
            return True
        print("⚠️ Não foi possível proteger a branch (pode precisar de permissões administrativas)")
        return False

    def enable_security_features(self) -> bool:
        """Enable secret scanning and other security features."""
        print("\n🔒 Ativando features de segurança...")

        # Dependabot alerts
        try:
            endpoint = f"https://api.github.com/repos/{self.owner}/{self.repo}/vulnerability-alerts"
            response = requests.put(endpoint, headers=self.headers)
            if response.status_code == 204:
                print("✅ Dependabot alerts ativado")
        except:
            print("⚠️ Dependabot não disponível (pode ser repositório privado ou plan insuficiente)")

        return True

    def run(self) -> bool:
        """Run all configuration steps."""
        print(f"\n🚀 Configurando {self.owner}/{self.repo}...")

        # Test connection
        try:
            resp = self._request("GET", "")
            if not resp:
                print("❌ Não foi possível acessar o repositório. Verifique o token e permissões.")
                return False
        except:
            print("❌ Erro ao conectar à API do GitHub")
            return False

        # Run configuration steps
        success = True
        success = self.enable_features() and success
        success = self.protect_main_branch() and success
        success = self.enable_security_features() and success

        if success:
            print("\n✅ Repositório configurado com sucesso!")
            print("\n📋 Próximos passos:")
            print("  1. Vá para https://github.com/{}/{}/settings/branches".format(self.owner, self.repo))
            print("  2. Verifique se a proteção da branch foi aplicada")
            print("  3. Crie categorias em Discussions (opcional)")
            print("  4. Configure Project Board para roadmap (opcional)")
        else:
            print("\n⚠️ Algumas configurações podem não ter sido aplicadas")
            print("   Veja as configurações manualmente em:")
            print(f"   https://github.com/{self.owner}/{self.repo}/settings")

        return success

def main():
    if len(sys.argv) < 4:
        print(__doc__)
        sys.exit(1)

    token = sys.argv[1]
    owner = sys.argv[2]
    repo = sys.argv[3]

    configurer = GitHubRepoConfigurer(token, owner, repo)
    success = configurer.run()
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
