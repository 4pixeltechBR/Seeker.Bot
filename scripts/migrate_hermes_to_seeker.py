#!/usr/bin/env python3
import os
import re
import shutil

HERMES_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "SeekerAgent"))

# Lista de renomeações de arquivos/diretórios físicos (origem relativa -> destino relativo)
PHYSICAL_RENAMES = [
    ("seeker_bootstrap.py", "seeker_bootstrap.py"),
    ("seeker_constants.py", "seeker_constants.py"),
    ("seeker_logging.py", "seeker_logging.py"),
    ("seeker_state.py", "seeker_state.py"),
    ("seeker_time.py", "seeker_time.py"),
    ("seeker_cli", "seeker_cli"),
    # Testes
    ("tests/test_hermes_bootstrap.py", "tests/test_seeker_bootstrap.py"),
    ("tests/test_hermes_constants.py", "tests/test_seeker_constants.py"),
    ("tests/test_hermes_home_profile_warning.py", "tests/test_seeker_home_profile_warning.py"),
    ("tests/test_hermes_logging.py", "tests/test_seeker_logging.py"),
    ("tests/test_hermes_state.py", "tests/test_seeker_state.py"),
    ("tests/test_hermes_state_compression_locks.py", "tests/test_seeker_state_compression_locks.py"),
    ("tests/test_hermes_state_wal_fallback.py", "tests/test_seeker_state_wal_fallback.py"),
]

# Regras de substituição de texto (Regex inteira -> substituto)
# Usamos \b para garantir limite de palavra e evitar quebrar links ou IDs de modelos
SUBSTITUTIONS = [
    (r"\bhermes_bootstrap\b", "seeker_bootstrap"),
    (r"\bhermes_constants\b", "seeker_constants"),
    (r"\bhermes_logging\b", "seeker_logging"),
    (r"\bhermes_state\b", "seeker_state"),
    (r"\bhermes_time\b", "seeker_time"),
    (r"\bhermes_cli\b", "seeker_cli"),
    (r"\bHermesAgent\b", "SeekerAgent"),
    (r"\bHERMES_HOME\b", "SEEKER_HOME"),
    (r"\bHERMES_DUMP_REQUESTS\b", "SEEKER_DUMP_REQUESTS"),
    (r"\bHERMES_DUMP_PROMPTS\b", "SEEKER_DUMP_PROMPTS"),
    (r"\bHERMES_DUMP_METRICS\b", "SEEKER_DUMP_METRICS"),
    (r"\bHERMES_TEST_MODE\b", "SEEKER_TEST_MODE"),
    (r"\bHERMES_API_KEY\b", "SEEKER_API_KEY"),
    (r"\bHERMES_BASE_URL\b", "SEEKER_BASE_URL"),
]

def rename_physical_files():
    print("--- 1. Renomeação de Arquivos e Pastas Físicas ---")
    for src_rel, dst_rel in PHYSICAL_RENAMES:
        src_path = os.path.join(HERMES_DIR, src_rel)
        dst_path = os.path.join(HERMES_DIR, dst_rel)
        
        if os.path.exists(src_path):
            print(f"Renomeando: {src_rel} -> {dst_rel}")
            try:
                # Remove se o destino já existir para evitar erro de colisão no Windows
                if os.path.exists(dst_path):
                    if os.path.isdir(dst_path):
                        shutil.rmtree(dst_path)
                    else:
                        os.remove(dst_path)
                os.rename(src_path, dst_path)
            except Exception as e:
                print(f"❌ Erro ao renomear {src_rel}: {e}")
        else:
            print(f"⚠️ Origem não encontrada (já renomeada ou ausente): {src_rel}")


def replace_content_references():
    print("\n--- 2. Substituição de Referências nos Arquivos ---")
    # Compilar as regexes para performance
    compiled_subs = [(re.compile(pattern), repl) for pattern, repl in SUBSTITUTIONS]
    
    count_modified = 0
    
    for root, dirs, files in os.walk(HERMES_DIR):
        if ".git" in root or ".venv" in root or "node_modules" in root:
            continue
            
        for file in files:
            path = os.path.join(root, file)
            # Ignora binários ou arquivos irrelevantes
            if not file.endswith(('.py', '.md', '.json', '.yaml', '.yml', '.txt', '.toml', '.sh', '.bat', '.ini', '.cfg')):
                continue
                
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                
                # Executa as substituições
                modified_content = content
                any_change = False
                for pattern, repl in compiled_subs:
                    if pattern.search(modified_content):
                        modified_content = pattern.sub(repl, modified_content)
                        any_change = True
                
                # Substituições complementares de texto avulso
                # Ex: "Seeker Agent" -> "Seeker Agent", mas com cuidado
                if "seeker_agent" in modified_content.lower():
                    # Substitui "Seeker Agent" e "Seeker CLI" preservando modelos
                    modified_content = re.sub(r"\bHermes Agent\b", "Seeker Agent", modified_content)
                    modified_content = re.sub(r"\bHermes CLI\b", "Seeker CLI", modified_content)
                    modified_content = re.sub(r"\bhermes agent\b", "seeker agent", modified_content)
                    # Altera strings de imports residuais (ex: import seeker_agent -> import seeker)
                    modified_content = re.sub(r"\bimport seeker_agent\b", "import seeker", modified_content)
                    any_change = True
                
                if any_change and modified_content != content:
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(modified_content)
                    rel_path = os.path.relpath(path, HERMES_DIR)
                    print(f"Modificado: {rel_path}")
                    count_modified += 1
            except Exception as e:
                print(f"❌ Erro ao ler/gravar {file}: {e}")
                
    print(f"\nTotal de arquivos modificados: {count_modified}")


def main():
    rename_physical_files()
    replace_content_references()
    print("\n--- Migração concluída com sucesso! ---")


if __name__ == "__main__":
    main()
