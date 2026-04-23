"""
Seeker.Bot — Obsidian Knowledge Graph Sync
src/core/memory/obsidian.py

Exporta o Knowledge Graph do Seeker para um Vault do Obsidian,
transformando entidades em notas e relacionamentos em [[WikiLinks]].
"""

import os
import re
import logging
from datetime import datetime
from src.core.memory.protocol import MemoryProtocol

log = logging.getLogger("seeker.memory.obsidian")

# Caracteres ilegais em nomes de arquivo (Windows + Obsidian)
_UNSAFE_CHARS = re.compile(r'[\\/:*?"<>|#^[\]{}]')


class ObsidianExporter:
    def __init__(self, memory: MemoryProtocol, vault_path: str):
        self.memory = memory
        self.vault_path = vault_path
        self.entities_path = os.path.join(vault_path, "Seeker", "Entities")

    def _safe_filename(self, name: str) -> str:
        """Sanitiza nome para uso seguro como filename no Windows/Obsidian."""
        return _UNSAFE_CHARS.sub("_", name).strip("_ .")[:100]

    async def sync_all(self):
        """Sincroniza todas as entidades e triplas para o Obsidian."""
        if not self.vault_path or not os.path.isdir(self.vault_path):
            log.debug("[obsidian] Vault path não existe, sync ignorado")
            return

        try:
            os.makedirs(self.entities_path, exist_ok=True)
        except OSError as e:
            log.warning(f"[obsidian] Falha ao criar diretório: {e}")
            return

        timeline = await self.memory.get_knowledge_timeline(limit=500)
        if not timeline:
            return

        entities_data: dict[str, dict] = {}

        for t in timeline:
            sub = t["sub_name"]
            obj = t["obj_name"]

            if sub not in entities_data:
                entities_data[sub] = {"type": "unknown", "triples": []}

            entities_data[sub]["triples"].append({
                "predicate": t["predicate"],
                "target": obj,
                "valid_from": t.get("valid_from"),
                "valid_to": t.get("valid_to")
            })

        exported = 0
        for name, data in entities_data.items():
            try:
                self._export_entity(name, data)
                exported += 1
            except Exception as e:
                log.warning(f"[obsidian] Falha ao exportar '{name}': {e}")

        if exported:
            log.info(f"[obsidian] Sync: {exported}/{len(entities_data)} entidades exportadas")

    def _export_entity(self, name: str, data: dict):
        filename = f"{self._safe_filename(name)}.md"
        filepath = os.path.join(self.entities_path, filename)

        content = [
            "---",
            f"type: {data.get('type', 'entity')}",
            f"exported_at: {datetime.now().isoformat()}",
            "tags: [seeker/entity]",
            "---",
            f"\n# {name}\n",
            "## Relacionamentos\n"
        ]

        for t in data["triples"]:
            valid = ""
            if t.get("valid_from"):
                valid = f" ({t['valid_from']} → {t.get('valid_to') or 'now'})"
            content.append(f"- **{t['predicate']}**: [[{t['target']}]]{valid}")

        content.append("\n\n---")
        content.append("*Nota gerada automaticamente pelo Seeker.Bot Knowledge Graph.*")

        with open(filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(content))
