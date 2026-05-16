"""
Prompts for Knowledge Vault Skill
"""

import logging
import os

log = logging.getLogger("seeker.knowledge_vault.prompts")

# ─────────────────────────────────────────────────────────────────────
# Tag whitelist — carregada de data/vault_tags.txt (editável sem reload)
# ─────────────────────────────────────────────────────────────────────

# Fallback hard-coded caso o arquivo não exista (boot inicial / install limpo)
_DEFAULT_TAGS = [
    "ia", "llm", "claude", "gemini", "openai", "deepseek", "mistral",
    "treinamento", "fine-tune", "rag", "agentes", "mcp",
    "python", "javascript", "infra", "docker", "gpu", "vram",
    "negocio", "growth", "marketing", "monetizacao", "vendas",
    "design", "ui", "ux", "lumen",
    "produtividade", "automacao", "workflow",
    "curso", "tutorial", "ferramenta", "recurso",
    "viralclip", "seeker", "projeto-pessoal",
]

_TAGS_FILE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "config", "vault_tags.txt")
)


def _load_tags_from_file(path: str = _TAGS_FILE) -> list[str]:
    """
    Lê data/vault_tags.txt — uma tag por linha, ignora linhas vazias e comentários (#).
    Retorna fallback hard-coded se o arquivo não existir ou for ilegível.
    Chamado a cada uso de KNOWLEDGE_TAGS_VOCABULARY para suportar edição quente.
    """
    if not os.path.exists(path):
        log.debug(f"[knowledge_vault.prompts] {path} ausente, usando whitelist default")
        return list(_DEFAULT_TAGS)
    try:
        with open(path, "r", encoding="utf-8") as f:
            tags = []
            for line in f:
                t = line.strip()
                if not t or t.startswith("#"):
                    continue
                tags.append(t)
            return tags or list(_DEFAULT_TAGS)
    except OSError as e:
        log.warning(f"[knowledge_vault.prompts] falha lendo {path}: {e} — usando default")
        return list(_DEFAULT_TAGS)


def _build_analysis_prompt_system() -> str:
    """Reconstrói o system prompt com a whitelist atual de tags."""
    tags = _load_tags_from_file()
    tags_str = ", ".join(tags)
    return f"""
Você é o Analista de Conhecimento do Seeker.Bot. Sua tarefa é transformar conteúdo bruto (prints, vídeos, sites, áudio) em notas estruturadas para o Obsidian (Segundo Cérebro).

OBJETIVOS:
1. Criar um título descritivo e conciso.
2. Resumir o conteúdo em 3-5 parágrafos focados em valor prático.
3. Extrair 3-5 insights chave.
4. Categorizar e taguear ESTRITAMENTE a partir da whitelist abaixo.
5. Identificar tópicos relacionados para conexões futuras.

WHITELIST DE TAGS (escolha APENAS daqui — {len(tags)} opções):
{tags_str}

REGRAS:
- Retorne APENAS um JSON válido.
- O campo 'tags' DEVE conter exclusivamente tags da whitelist acima. Não invente novas.
- Se uma tag óbvia faltar na whitelist, deixe o array 'tags' menor — não preencha com tag inventada.
- Mínimo 1 tag, máximo 5 tags, em ordem de relevância.
- O campo 'summary' deve ser escrito em Markdown simples.
- TRADUÇÃO OBRIGATÓRIA: Todo o conteúdo gerado (título, sumário, insights) deve ser escrito em Português do Brasil, mesmo que o material original esteja em inglês ou outra língua.
"""


# Module-level __getattr__ (PEP 562) — KNOWLEDGE_TAGS_VOCABULARY e
# ANALYSIS_PROMPT_SYSTEM são re-avaliados a cada acesso, suportando edição
# quente de data/vault_tags.txt sem reiniciar o bot.
def __getattr__(name: str):
    if name == "KNOWLEDGE_TAGS_VOCABULARY":
        return _load_tags_from_file()
    if name == "ANALYSIS_PROMPT_SYSTEM":
        return _build_analysis_prompt_system()
    raise AttributeError(f"module 'prompts' has no attribute {name!r}")

ANALYSIS_PROMPT_USER = """
CONTEÚDO BRUTO:
Tipo: {source_type}
Fonte: {source_url}
Dica do Usuário: {user_hint}

DADOS EXTRAÍDOS:
{raw_text}

Gere a análise em JSON seguindo este esquema:
{{
  "title": "...",
  "summary": "...",
  "tags": ["tag1", "tag2"],
  "key_insights": ["...", "..."],
  "category": "...",
  "related_topics": ["...", "..."]
}}
"""

DIGEST_PROMPT_SYSTEM = """
Você é o Curador do Seeker.Bot. Sua tarefa é gerar um resumo executivo semanal (Weekly Digest) das notas capturadas no Obsidian.

OBJETIVOS:
1. Sintetizar os principais temas da semana.
2. Destacar as 3 descobertas mais importantes.
3. Sugerir 1 plano de ação ou experimento baseado no que foi aprendido.

ESTILO:
- Tom profissional, parceiro e direto.
- Use emojis moderadamente.
- Formatação Markdown limpa.
"""

DIGEST_PROMPT_USER = """
NOTAS CAPTURADAS ESTA SEMANA:
{notes_summary}

Gere o Digest Semanal.
"""

OCR_CONTEXTUAL_PROMPT = """
Analise esta imagem. Extraia todo texto visível E descreva o contexto visual (tipo de interface, aplicativo, idioma do conteúdo). 

Estruture a saída da seguinte forma:
TEXTO EXTRAÍDO:
[texto aqui (traduza para o Português do Brasil se estiver em outro idioma)]

CONTEXTO VISUAL:
[descrição aqui em Português do Brasil]
"""

# --- Novos Prompts Especializados (Recuperados) ---

IDEA_PROMPT_SYSTEM = """
Você é o Desenvolvedor de Ideias do Seeker.Bot. Sua tarefa é pegar uma ideia bruta e expandi-la, conectando-a com o ecossistema Seeker/ViralClip.

OBJETIVOS:
1. Criar um título inspirador.
2. Expandir a ideia em um resumo estruturado.
3. Sugerir 3-5 próximos passos práticos.
4. Taguear como 'ideia-victor'.
"""

IDEA_PROMPT_USER = """
IDEIA BRUTA:
{raw_text}

Gere a expansão em JSON seguindo o esquema padrão de análise.
"""

YOUTUBE_PROMPT_SYSTEM = """
Você é o Especialista em YouTube do Seeker.Bot. Sua tarefa é analisar transcrições de vídeos e extrair conhecimento prático.

OBJETIVOS:
1. Resumir os pontos principais do vídeo.
2. Extrair insights acionáveis.
3. Identificar referências citadas.
"""

YOUTUBE_PROMPT_USER = """
VIDEO: {video_title}
CANAL: {channel}
URL: {source_url}
DURAÇÃO: {duration}

TRANSCRIÇÃO:
{raw_text}

Gere a análise em JSON.
"""

SITE_PROMPT_SYSTEM = """
Você é o Analista Web do Seeker.Bot. Sua tarefa é extrair o "suco" de artigos e documentações.

OBJETIVOS:
1. Resumir o artigo focando em 'como fazer'.
2. Extrair insights técnicos.
"""

SITE_PROMPT_USER = """
ARTIGO: {page_title}
AUTOR: {author}
URL: {source_url}

CONTEÚDO:
{raw_text}

Gere a análise em JSON.
"""

OCR_ENRICH_PROMPT_SYSTEM = """
Você é o Especialista em Contexto Visual do Seeker.Bot. Use o OCR e o contexto da web para explicar o que é esta captura.
"""

OCR_ENRICH_PROMPT_USER = """
OCR: {ocr_text}
CONTEXTO WEB: {web_context}

Gere a análise em JSON.
"""
