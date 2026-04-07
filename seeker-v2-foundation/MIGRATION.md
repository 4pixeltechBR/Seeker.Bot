# Seeker.Bot — Guia de Migração para Fundação V2

> Passo-a-passo para substituir os arquivos em `E:\Seeker.Bot`
> Tempo estimado: 15-20 minutos
> Risco: BAIXO (backup automático, rollback fácil)

---

## ANTES DE COMEÇAR

```powershell
# 1. Para o bot (se estiver rodando)
# Ctrl+C no terminal ou para o watchdog

# 2. Backup completo
cd E:\
xcopy Seeker.Bot Seeker.Bot.backup /E /I /H
# Agora tem E:\Seeker.Bot.backup como rollback
```

---

## PASSO 1 — Arquivo novo na RAIZ

| Ação | Arquivo | Destino |
|------|---------|---------|
| **CRIAR** | `pyproject.toml` | `E:\Seeker.Bot\pyproject.toml` |

Este arquivo é novo. Cola na raiz do projeto.

---

## PASSO 2 — Arquivos novos em `src/`

| Ação | Arquivo | Destino |
|------|---------|---------|
| **CRIAR** | `__init__.py` | `E:\Seeker.Bot\src\__init__.py` |
| **CRIAR** | `__main__.py` | `E:\Seeker.Bot\src\__main__.py` |
| **CRIAR** | `__init__.py` | `E:\Seeker.Bot\src\core\__init__.py` |
| **CRIAR** | `__init__.py` | `E:\Seeker.Bot\src\core\cognition\__init__.py` |
| **CRIAR** | `__init__.py` | `E:\Seeker.Bot\src\core\phases\__init__.py` |
| **CRIAR** | `__init__.py` | `E:\Seeker.Bot\src\core\evidence\__init__.py` |
| **CRIAR** | `__init__.py` | `E:\Seeker.Bot\src\core\healing\__init__.py` |
| **CRIAR** | `__init__.py` | `E:\Seeker.Bot\src\core\memory\__init__.py` |
| **CRIAR** | `__init__.py` | `E:\Seeker.Bot\src\core\router\__init__.py` |
| **CRIAR** | `__init__.py` | `E:\Seeker.Bot\src\core\search\__init__.py` |
| **CRIAR** | `__init__.py` | `E:\Seeker.Bot\src\channels\__init__.py` |
| **CRIAR** | `__init__.py` | `E:\Seeker.Bot\src\channels\telegram\__init__.py` |
| **CRIAR** | `__init__.py` | `E:\Seeker.Bot\src\providers\__init__.py` |
| **CRIAR** | `__init__.py` | `E:\Seeker.Bot\config\__init__.py` |

Todos os `__init__.py` são arquivos VAZIOS (0 bytes).
Se algum já existir, não sobrescreve.

```powershell
# Script rápido pra criar todos:
cd E:\Seeker.Bot
echo. > src\__init__.py
echo. > src\__main__.py
echo. > src\core\__init__.py
echo. > src\core\cognition\__init__.py
echo. > src\core\phases\__init__.py
echo. > src\core\evidence\__init__.py
echo. > src\core\healing\__init__.py
echo. > src\core\memory\__init__.py
echo. > src\core\router\__init__.py
echo. > src\core\search\__init__.py
echo. > src\channels\__init__.py
echo. > src\channels\telegram\__init__.py
echo. > src\providers\__init__.py
echo. > config\__init__.py
```

Depois substitua o `src\__main__.py` pelo conteúdo real (arquivo do download).

---

## PASSO 3 — Módulos NOVOS (não existem ainda)

| Ação | Arquivo | Destino |
|------|---------|---------|
| **CRIAR** | `protocol.py` | `E:\Seeker.Bot\src\core\memory\protocol.py` |
| **CRIAR** | `session.py` | `E:\Seeker.Bot\src\core\memory\session.py` |
| **CRIAR** | `prompts.py` | `E:\Seeker.Bot\src\core\cognition\prompts.py` |
| **CRIAR** | `base.py` | `E:\Seeker.Bot\src\core\phases\base.py` |
| **CRIAR** | `reflex.py` | `E:\Seeker.Bot\src\core\phases\reflex.py` |
| **CRIAR** | `deliberate.py` | `E:\Seeker.Bot\src\core\phases\deliberate.py` |
| **CRIAR** | `deep.py` | `E:\Seeker.Bot\src\core\phases\deep.py` |

Estes são todos novos. Cria as pastas se não existirem:

```powershell
mkdir E:\Seeker.Bot\src\core\cognition 2>$null
mkdir E:\Seeker.Bot\src\core\phases 2>$null
```

Depois cola cada arquivo no destino.

---

## PASSO 4 — Arquivos SUBSTITUÍDOS (existem, precisam ser trocados)

| Ação | Arquivo | Destino | O que muda |
|------|---------|---------|------------|
| **SUBSTITUIR** | `store.py` | `src\core\memory\store.py` | +tabelas embeddings/session, +métodos Protocol, WAL mode |
| **SUBSTITUIR** | `embeddings.py` | `src\core\memory\embeddings.py` | Persistência no SQLite, batch load no startup |
| **SUBSTITUIR** | `decay.py` | `src\core\evidence\decay.py` | Usa Protocol ao invés de `_db` direto |
| **SUBSTITUIR** | `arbitrage.py` | `src\core\evidence\arbitrage.py` | ClaimComparator V2 com embeddings |
| **SUBSTITUIR** | `pipeline.py` | `src\core\pipeline.py` | Orquestrador fino, delega pra phases |
| **SUBSTITUIR** | `base.py` | `src\providers\base.py` | Connection pooling global |
| **SUBSTITUIR** | `bot.py` | `src\channels\telegram\bot.py` | Sem sys.path hack, session_id, cleanup |

**ATENÇÃO:** Faça backup individual ANTES de cada substituição:

```powershell
# No diretório E:\Seeker.Bot, renomeia os originais:
ren src\core\memory\store.py store_v1.py
ren src\core\memory\embeddings.py embeddings_v1.py
ren src\core\evidence\decay.py decay_v1.py
ren src\core\evidence\arbitrage.py arbitrage_v1.py
ren src\core\pipeline.py pipeline_v1.py
ren src\providers\base.py base_v1.py
ren src\channels\telegram\bot.py bot_v1.py

# Depois cola os novos nos mesmos caminhos
```

---

## PASSO 5 — Arquivos que NÃO MUDAM

| Arquivo | Status |
|---------|--------|
| `config/models.py` | ✅ Sem mudança |
| `config/.env` | ✅ Sem mudança |
| `src/core/healing/judge.py` | ✅ Sem mudança |
| `src/core/memory/extractor.py` | ✅ Sem mudança |
| `src/core/router/cognitive_load.py` | ✅ Sem mudança |
| `src/core/search/web.py` | ✅ Sem mudança |
| `src/channels/telegram/formatter.py` | ✅ Sem mudança |
| `scripts/watchdog.ps1` | ✅ Sem mudança |
| `scripts/setup_watchdog.ps1` | ✅ Sem mudança |
| `tests/test_router.py` | ✅ Sem mudança |
| `data/seeker_memory.db` | ✅ Sem mudança (novas tabelas criadas auto) |

---

## PASSO 6 — Instalar como package

```powershell
cd E:\Seeker.Bot

# Ativa o venv
.venv\Scripts\Activate.ps1

# Instala o projeto em modo editável
pip install -e .

# Testa se os imports funcionam
python -c "from src.core.pipeline import SeekerPipeline; print('OK')"
```

Se o `pip install -e .` der certo e o teste imprimir `OK`,
os imports estão funcionando sem `sys.path.insert`.

---

## PASSO 7 — Primeiro boot

```powershell
# Roda o bot pela nova forma:
python -m src

# Ou pela forma antiga (ainda funciona):
python src/channels/telegram/bot.py
```

**O que esperar no primeiro boot:**

```
[memory] DB: ...\data\seeker_memory.db | X episódios, Y fatos, 0 embeddings
[semantic] 0 embeddings carregados do disco
[semantic] Indexando Y fatos novos...
[semantic] Y fatos indexados (Y total)
[pipeline] Semantic search com Gemini Embedding 2 ativo
[pipeline] Inicializado com session context + embeddings persistidos
Seeker.Bot iniciado
  Memória persistente ativa
  Session context ativo
  Embeddings persistidos
  Aguardando mensagens...
```

Na primeira vez, o sistema vai indexar todos os fatos existentes (chama a API de embedding).
A partir do segundo boot, carrega do disco sem chamar API nenhuma.

---

## PASSO 8 — Testar

1. Manda uma mensagem qualquer pro bot → deve responder normalmente
2. Manda outra mensagem referenciando a anterior ("e o custo disso?") → deve ter contexto
3. `/status` → deve mostrar "Sessões ativas: 1"
4. `/memory` → deve funcionar igual
5. `/decay` → deve mostrar "Sessões limpas: 0" (campo novo)
6. Reinicia o bot → manda mensagem → `python -m src` deve funcionar
7. Após restart, check logs: "X embeddings carregados do disco" (não "indexando")

---

## ROLLBACK (se algo der errado)

```powershell
# Opção 1: restaura arquivo individual
cd E:\Seeker.Bot
ren src\core\pipeline.py pipeline_v2.py
ren src\core\pipeline_v1.py pipeline.py

# Opção 2: restaura tudo
xcopy E:\Seeker.Bot.backup E:\Seeker.Bot /E /I /H /Y
```

---

## MIGRAÇÃO DO BANCO (automática)

As novas tabelas (`fact_embeddings` e `session_turns`) são criadas com
`CREATE TABLE IF NOT EXISTS` — então o banco existente (`seeker_memory.db`)
é migrado automaticamente no primeiro boot. Zero perda de dados.

O `PRAGMA journal_mode=WAL` também é aplicado automaticamente
(melhor performance para reads concorrentes).

---

## RESUMO VISUAL

```
E:\Seeker.Bot\
├── pyproject.toml                         ← NOVO
├── src/
│   ├── __init__.py                        ← NOVO (vazio)
│   ├── __main__.py                        ← NOVO
│   ├── core/
│   │   ├── __init__.py                    ← NOVO (vazio)
│   │   ├── pipeline.py                    ← SUBSTITUÍDO
│   │   ├── cognition/
│   │   │   ├── __init__.py                ← NOVO (vazio)
│   │   │   └── prompts.py                 ← NOVO
│   │   ├── phases/
│   │   │   ├── __init__.py                ← NOVO (vazio)
│   │   │   ├── base.py                    ← NOVO
│   │   │   ├── reflex.py                  ← NOVO
│   │   │   ├── deliberate.py              ← NOVO
│   │   │   └── deep.py                    ← NOVO
│   │   ├── evidence/
│   │   │   ├── __init__.py                ← NOVO (vazio)
│   │   │   ├── arbitrage.py               ← SUBSTITUÍDO
│   │   │   └── decay.py                   ← SUBSTITUÍDO
│   │   ├── memory/
│   │   │   ├── __init__.py                ← NOVO (vazio)
│   │   │   ├── protocol.py                ← NOVO
│   │   │   ├── store.py                   ← SUBSTITUÍDO
│   │   │   ├── embeddings.py              ← SUBSTITUÍDO
│   │   │   ├── session.py                 ← NOVO
│   │   │   └── extractor.py               ✅ sem mudança
│   │   ├── healing/
│   │   │   ├── __init__.py                ← NOVO (vazio)
│   │   │   └── judge.py                   ✅ sem mudança
│   │   ├── router/
│   │   │   ├── __init__.py                ← NOVO (vazio)
│   │   │   └── cognitive_load.py          ✅ sem mudança
│   │   └── search/
│   │       ├── __init__.py                ← NOVO (vazio)
│   │       └── web.py                     ✅ sem mudança
│   ├── channels/
│   │   ├── __init__.py                    ← NOVO (vazio)
│   │   └── telegram/
│   │       ├── __init__.py                ← NOVO (vazio)
│   │       ├── bot.py                     ← SUBSTITUÍDO
│   │       └── formatter.py               ✅ sem mudança
│   └── providers/
│       ├── __init__.py                    ← NOVO (vazio)
│       └── base.py                        ← SUBSTITUÍDO
├── config/
│   ├── __init__.py                        ← NOVO (vazio)
│   ├── .env                               ✅ sem mudança
│   └── models.py                          ✅ sem mudança
├── tests/                                 ✅ sem mudança
├── scripts/                               ✅ sem mudança
└── data/
    └── seeker_memory.db                   ✅ migração automática
```
