"""
Seeker.Bot — Cortex Manager
src/core/memory/cortex_manager.py

Gerencia o acesso ao armazenamento em disco do pipeline Cortex.
Isola I/O de arquivos para manter o core (pipeline.py e goals) focado na lógica de negócio.
"""

import os
import json
import time
import logging

log = logging.getLogger("seeker.memory.cortex_manager")

class CortexManager:
    """
    Controla o staging de insights e a leitura/escrita da memória curada.
    """
    def __init__(self, data_dir: str | None = None):
        if data_dir:
            self.data_dir = data_dir
        else:
            base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
            self.data_dir = os.path.join(base, "data", "cortex")
            
        os.makedirs(self.data_dir, exist_ok=True)
        
        self.insights_file = os.path.join(self.data_dir, "insights.jsonl")
        self.curated_file = os.path.join(self.data_dir, "curated_knowledge.md")
        
        self.target_categories = {"reflexive_rule", "decision", "pattern", "project", "user_pref"}
        self._cache = {"content": "", "timestamp": 0}

    # ==========================================
    # STAGING AREA (Insights)
    # ==========================================

    def stage_insights(
        self, 
        session_id: str, 
        facts: list[dict], 
        triples: list[dict],
        source: str = "conversation"
    ) -> int:
        """Adiciona insights extraídos ao staging."""
        insights_to_log = []
        now = time.time()
        
        for f in facts:
            cat = f.get("category", "")
            if cat in self.target_categories or "sempre" in f.get("fact", "").lower():
                insights_to_log.append({
                    "ts": now,
                    "type": cat or "general_insight",
                    "fact": f.get("fact"),
                    "source": source,
                    "session_id": session_id
                })
                
        for t in triples:
            if t.get("valid_from"):
                insights_to_log.append({
                    "ts": now,
                    "type": "temporal_relationship",
                    "triple": {
                        "subject": t.get("subject"),
                        "predicate": t.get("predicate"),
                        "object": t.get("object_") or t.get("object"),
                        "valid_from": t.get("valid_from")
                    },
                    "source": source,
                    "session_id": session_id
                })
                
        if not insights_to_log:
            return 0
            
        try:
            with open(self.insights_file, "a", encoding="utf-8") as f:
                for insight in insights_to_log:
                    f.write(json.dumps(insight, ensure_ascii=False) + "\n")
            log.info(f"[cortex_manager] {len(insights_to_log)} insights enviados para o staging")
            return len(insights_to_log)
        except Exception as e:
            log.error(f"[cortex_manager] Falha ao escrever staging: {e}")
            return 0

    def get_staging_insights(self) -> list[dict]:
        """Lê todos os insights pendentes no staging."""
        if not os.path.exists(self.insights_file):
            return []
        
        insights = []
        try:
            with open(self.insights_file, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        insights.append(json.loads(line))
        except Exception as e:
            log.error(f"[cortex_manager] Erro ao ler insights: {e}")
        return insights

    def clear_staging(self) -> None:
        """Esvazia o arquivo de staging após consolidação."""
        try:
            with open(self.insights_file, "w", encoding="utf-8") as f:
                f.truncate(0)
        except Exception as e:
            log.error(f"[cortex_manager] Erro ao limpar staging: {e}")

    # ==========================================
    # CURATED KNOWLEDGE (Long Term Memory)
    # ==========================================

    def get_curated_knowledge(self, cached: bool = True) -> str:
        """Retorna o conteúdo consolidado (com cache opcional)."""
        now = time.time()
        
        if cached and (now - self._cache["timestamp"] <= 3600):
            return self._cache["content"]
            
        if not os.path.exists(self.curated_file):
            self._cache["content"] = ""
            self._cache["timestamp"] = now
            return ""
            
        try:
            with open(self.curated_file, "r", encoding="utf-8") as f:
                content = f.read()
                if content and len(content) > 10:
                    self._cache["content"] = f"=== L0.5: CURATED KNOWLEDGE ===\n{content}"
                else:
                    self._cache["content"] = ""
        except Exception as e:
            log.error(f"[cortex_manager] Erro ao ler curated knowledge: {e}")
            self._cache["content"] = ""
            
        self._cache["timestamp"] = now
        return self._cache["content"]

    def write_curated_knowledge(self, content: str) -> None:
        """
        Salva o novo conhecimento consolidado e atualiza o cache.
        Aplica limite estrutural para evitar estouro de token no longo prazo.
        """
        try:
            # Limite de segurança de ~5000 chars para evitar Lost in the Middle
            if len(content) > 5000:
                content = content[:5000] + "\n\n... (truncado por limite estrutural)"
                
            with open(self.curated_file, "w", encoding="utf-8") as f:
                f.write(content.strip())
                
            # Atualiza o cache imediatamente para uso no pipeline
            self._cache["content"] = f"=== L0.5: CURATED KNOWLEDGE ===\n{content.strip()}"
            self._cache["timestamp"] = time.time()
        except Exception as e:
            log.error(f"[cortex_manager] Erro ao escrever curated knowledge: {e}")
