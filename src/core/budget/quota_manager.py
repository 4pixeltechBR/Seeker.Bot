"""
Seeker.Bot — Quota & Credits Manager
src/core/budget/quota_manager.py

Gerencia saldos de créditos (prepaid) e cotas mensais (search, free tiers).
"""

import json
import logging
import os
from datetime import datetime

log = logging.getLogger("seeker.budget.quota")

class QuotaManager:
    """
    Monitor de cotas e créditos.
    Lida com créditos financeiros (DeepSeek) e limites de uso (Tavily/Brave).
    """

    def __init__(self, data_path: str = None):
        if data_path is None:
            data_path = os.path.join(os.getcwd(), "data", "quotas.json")
        self.data_path = data_path
        os.makedirs(os.path.dirname(self.data_path), exist_ok=True)
        self.quotas = self._load()

    def _load(self) -> dict:
        if os.path.exists(self.data_path):
            try:
                with open(self.data_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                log.error(f"Erro ao carregar quotas.json: {e}")
        
        # Default inicial (exemplo de estrutura)
        return {
            "deepseek": {"type": "prepaid", "balance": 0.0, "currency": "USD", "alert_at": 1.0},
            "gemini": {"type": "daily", "limit": 500, "used": 0, "reset_date": ""},
            "tavily": {"type": "monthly", "limit": 1000, "used": 0, "reset_month": ""},
            "brave": {"type": "monthly", "limit": 1000, "used": 0, "reset_month": ""},
        }

    def _save(self):
        try:
            with open(self.data_path, "w", encoding="utf-8") as f:
                json.dump(self.quotas, f, indent=2)
        except Exception as e:
            log.error(f"Erro ao salvar quotas.json: {e}")

    def consume_financial(self, provider: str, cost_usd: float):
        """Consome saldo financeiro (créditos pagos)"""
        if provider in self.quotas and self.quotas[provider]["type"] == "prepaid":
            self.quotas[provider]["balance"] -= cost_usd
            self._save()
            
            # Alerta se estiver acabando
            balance = self.quotas[provider]["balance"]
            alert_at = self.quotas[provider].get("alert_at", 1.0)
            if balance < alert_at:
                log.warning(f"[quota] Saldo de {provider} baixo: ${balance:.2f}")
                return True # Sinaliza necessidade de alerta
        return False

    def consume_usage(self, key: str, count: int = 1):
        """Consome cota de uso (requests/queries)"""
        if key not in self.quotas:
            return False

        q = self.quotas[key]
        now = datetime.now()

        # Reset mensal
        if q["type"] == "monthly":
            current_month = now.strftime("%Y-%m")
            if q.get("reset_month") != current_month:
                q["used"] = 0
                q["reset_month"] = current_month
        
        # Reset diário
        elif q["type"] == "daily":
            current_day = now.strftime("%Y-%m-%d")
            if q.get("reset_date") != current_day:
                q["used"] = 0
                q["reset_date"] = current_day

        q["used"] += count
        self._save()

        # Alerta se estiver próximo do limite (>90%)
        if q["used"] / q["limit"] > 0.9:
            log.warning(f"[quota] Cota de {key} quase esgotada: {q['used']}/{q['limit']}")
            return True
        return False

    def set_balance(self, provider: str, amount: float):
        """Atualiza manualmente o saldo (ex: após recarga)"""
        if provider not in self.quotas:
            self.quotas[provider] = {"type": "prepaid", "balance": 0.0, "currency": "USD", "alert_at": 1.0}
        self.quotas[provider]["balance"] = amount
        self._save()

    def get_all_status(self) -> dict:
        return self.quotas
