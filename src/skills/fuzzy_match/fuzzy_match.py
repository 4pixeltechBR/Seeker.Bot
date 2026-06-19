import os
import logging

log = logging.getLogger("seeker.fuzzy_match")

class FuzzyMatcher:
    """Implementa busca aproximada e auto-correção de caminhos de arquivos baseada em distância de edição (Levenshtein)."""

    def __init__(self, pipeline):
        self.pipeline = pipeline

    def levenshtein_distance(self, s1: str, s2: str) -> int:
        """Calcula a distância de Levenshtein entre duas strings."""
        if len(s1) < len(s2):
            return self.levenshtein_distance(s2, s1)

        if len(s2) == 0:
            return len(s1)

        previous_row = range(len(s2) + 1)
        for i, c1 in enumerate(s1):
            current_row = [i + 1]
            for j, c2 in enumerate(s2):
                insertions = previous_row[j + 1] + 1
                deletions = current_row[j] + 1
                substitutions = previous_row[j] + (c1 != c2)
                current_row.append(min(insertions, deletions, substitutions))
            previous_row = current_row

        return previous_row[-1]

    def find_closest_path(self, target_path: str, search_dir: str = ".") -> str:
        """
        Varre o diretório à procura do caminho físico mais próximo do alvo informado.
        Se existir fisicamente, retorna o próprio caminho.
        """
        # Limpa e normaliza caminhos
        target_path = os.path.normpath(target_path.strip().strip('"').strip("'"))
        if os.path.exists(target_path):
            return target_path

        log.info(f"[fuzzy_match] Caminho '{target_path}' não existe fisicamente. Iniciando busca aproximada...")

        # Coleta lista de arquivos do diretório base
        target_filename = os.path.basename(target_path)
        best_match = None
        min_dist = 9999

        # Varre recursivamente com limite de profundidade de subpastas para performance
        max_depth = 3
        base_depth = search_dir.count(os.sep)

        for root, dirs, files in os.walk(search_dir):
            # Ignora pastas de controle
            for ignore in [".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache"]:
                if ignore in dirs:
                    dirs.remove(ignore)

            depth = root.count(os.sep) - base_depth
            if depth > max_depth:
                del dirs[:] # Para recursão profunda
                continue

            for file in files:
                # Calcula distância apenas para o nome do arquivo (basename)
                dist = self.levenshtein_distance(target_filename.lower(), file.lower())
                if dist < min_dist:
                    min_dist = dist
                    best_match = os.path.join(root, file)

        # Tolerância: se a distância for muito grande, não corrige (ex: max 4 caracteres de diferença)
        if best_match and min_dist <= 4:
            log.info(f"[fuzzy_match] Auto-corrigido: '{target_path}' ➔ '{best_match}' (dist={min_dist})")
            return best_match

        return target_path
