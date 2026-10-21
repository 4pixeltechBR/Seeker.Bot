# Seeker

Version 1.0.0. Personal desktop agent for Windows. One Python process, a WebView2 window, and online models. It talks, reads files, researches with sources, watches mail and the clock, and waits for a yes before it changes anything that matters.

The window has three columns: agenda on the left, the conversation in the center, and the current work on the right. The center is **Chat** or **Voice**.

## What it does

- Talks through Gemini, then Maritaca, then NVIDIA. The order is in `config.toml`. A missing key skips that provider.
- Reads the folders listed in `roots`. `.env` stays out of the file tools.
- `research` is a web fact and only counts when it comes back with numbered sources. Without a source, it says it does not know. `read_page` reads a public page. `read_feed` reads RSS or Atom. `last30days` lists what people engaged with in the last 30 days on Hacker News, Reddit, GitHub, and Polymarket.
- The right-hand terminal is one continuous PowerShell session. A typed command runs immediately. A command the agent asks for also runs immediately, except when it deletes, overwrites, formats, stops a process, shuts the PC down, or runs `git clean`, `git reset --hard`, or `git push --force`. A yes in the chat is enough for those.
- News at 07:30 and 19:30, a Radar card at 08:30, mail at 09:00 and 21:00, a curiosity note at 18:00, and a tech scout at 22:00. Times are America/Sao_Paulo. An empty result stays quiet. Disks C, D, E, F, and H are checked every 6 hours and reported only above 95%.
- Mail can be read freely. A draft, a send, and a delete wait for a yes and show the recipient, subject, and body.
- Telegram uses the same agent when `TELEGRAM_BOT_TOKEN` and `TELEGRAM_ALLOWED_USERS` are set. Only that user gets in. Text is the default. Voice sends the written reply plus one OGG Opus note. The PC has to be on, and `ffmpeg` has to be on PATH.
- A routine runs by itself at its time, with read and search only. It does not run commands or send mail.
- MCP: copy `mcp.example.json` to `mcp.json`, or paste the JSON in the chat. Connecting a server waits for a yes. Reads run. Writes wait again.
- The `cerebro` folder is a local Obsidian vault: diary, lessons, and short notes. It is not part of this repository.
- A YouTube link or a topic can be saved through the knowledge vault after a yes.
- Voice uses local Kokoro (`pm_santa` on CUDA when there is room). Transcription tries Groq Whisper, then Gemini.
- To store an API key, ask in the chat. A masked card opens beside the conversation. The value never enters the transcript and never comes back to the model. A yes in the chat does not save it. The card button does.

Closing the window leaves the process in the tray. **Sair** quits.

## Start

Requires Windows, Python 3.12, and the WebView2 runtime.

```bat
start.bat
```

The first run creates `.venv`, copies `.env.example` to `.env`, and copies `config.example.toml` to `config.toml` when that file is missing. Put at least one key in `.env`:

```
GEMINI_API_KEY=
MARITACA_API_KEY=
NVIDIA_API_KEY=
```

One key is enough. Without Gemini, web research and the Gemini transcription fallback stay off.

`.env.example` also has empty slots for the free-tier providers in [awesome-ai-free-tiers](https://github.com/4pixeltechBR/awesome-ai-free-tiers): Mistral, OpenRouter, DeepSeek, SiliconFlow, Hyperbolic, Fireworks, SambaNova, Cohere, Hugging Face, Inception, Reka, Cloudflare, Zhipu, StepFun, and 01.AI, plus Tavily, Exa, and Jina for search, and Deepgram, AssemblyAI, ElevenLabs, and Cartesia for audio. An empty line stays off. The chat cascade uses only the provider blocks in `config.toml`. Ask in the chat to store a key in the masked card.

Add your own folders under `roots` in `config.toml`. Restart after changing roots or keys from the file. A key saved in the secure card is picked up by the running app.

## Tests

```bat
.venv\Scripts\python.exe -m pytest
```

## What stays off GitHub

`.env`, `mcp.json`, `config.toml`, `data/`, `logs/`, and `cerebro/` stay on the machine. They hold keys, the mailbox, the chat database, and private notes.

## License

Apache License 2.0. See [LICENSE](LICENSE).

---

# Seeker

Versão 1.0.0. Agente pessoal para Windows. Um processo Python, uma janela WebView2 e modelos online. Ele conversa, lê arquivos, pesquisa com fonte, olha o e-mail e o relógio, e espera um sim antes de mudar o que importa.

A janela tem três colunas: agenda à esquerda, conversa no centro e o trabalho atual à direita. No centro, **Chat** ou **Voz**.

## O que ele faz

- Conversa pelo Gemini, depois Maritaca, depois NVIDIA. A ordem está em `config.toml`. Chave ausente pula o provedor.
- Lê as pastas de `roots`. O arquivo `.env` fica fora das ferramentas de arquivo.
- `research` é um fato da web e só vale com fontes numeradas. Sem fonte, ele diz que não sabe. `read_page` lê uma página pública. `read_feed` lê RSS ou Atom. `last30days` lista o que as pessoas engajaram nos últimos 30 dias no Hacker News, Reddit, GitHub e Polymarket.
- O terminal da direita é um PowerShell contínuo. O comando digitado roda na hora. O comando que o agente pede também roda na hora, salvo quando apaga, sobrescreve, formata, encerra um processo, desliga o PC ou faz `git clean`, `git reset --hard` e `git push --force`. Um sim no chat basta.
- Notícias às 07:30 e 19:30, Radar às 08:30, e-mail às 09:00 e 21:00, curiosidade às 18:00 e reconhecimento técnico às 22:00. O fuso é America/Sao_Paulo. Sem resultado, fica quieto. Os discos C, D, E, F e H são olhados a cada 6 horas e só avisam acima de 95%.
- Ler o e-mail é livre. Rascunho, envio e exclusão esperam um sim e mostram destinatário, assunto e texto.
- O Telegram usa o mesmo agente quando `TELEGRAM_BOT_TOKEN` e `TELEGRAM_ALLOWED_USERS` estão preenchidos. Só esse usuário entra. O padrão é texto. Voz manda a resposta escrita e um único áudio OGG Opus. O PC precisa estar ligado, e o `ffmpeg` precisa estar no PATH.
- Uma rotina roda sozinha no horário, só com leitura e pesquisa. Ela não roda comando nem envia e-mail.
- MCP: copie `mcp.example.json` para `mcp.json`, ou cole o JSON no chat. Conectar um servidor espera um sim. Leitura segue. Escrita espera de novo.
- A pasta `cerebro` é um cofre local do Obsidian: diário, lições e notas curtas. Ela não entra neste repositório.
- Um link de vídeo ou um tema pode ir para o cofre de conhecimento depois de um sim.
- A voz é o Kokoro local (`pm_santa` na CUDA quando há espaço). A transcrição tenta o Groq Whisper e depois o Gemini.
- Para guardar uma chave, peça no chat. Um cartão mascarado abre ao lado da conversa. O valor não entra no histórico e não volta para o modelo. Um sim no chat não grava. O botão do cartão grava.

Fechar a janela deixa o processo na bandeja. **Sair** encerra.

## Começar

Precisa de Windows, Python 3.12 e do runtime WebView2.

```bat
start.bat
```

Na primeira vez ele cria o `.venv`, copia `.env.example` para `.env` e, se não houver `config.toml`, copia `config.example.toml`. Coloque pelo menos uma chave no `.env`:

```
GEMINI_API_KEY=
MARITACA_API_KEY=
NVIDIA_API_KEY=
```

Uma chave basta. Sem o Gemini, a pesquisa na web e a transcrição de reserva ficam desligadas.

O `.env.example` também tem vagas vazias para os provedores do catálogo [awesome-ai-free-tiers](https://github.com/4pixeltechBR/awesome-ai-free-tiers): Mistral, OpenRouter, DeepSeek, SiliconFlow, Hyperbolic, Fireworks, SambaNova, Cohere, Hugging Face, Inception, Reka, Cloudflare, Zhipu, StepFun e 01.AI, além de Tavily, Exa e Jina para busca, e Deepgram, AssemblyAI, ElevenLabs e Cartesia para áudio. Linha vazia fica desligada. A cascata da conversa usa só os blocos de provedor do `config.toml`. Peça no chat para guardar uma chave no cartão mascarado.

Acrescente as suas pastas em `roots`, no `config.toml`. Reinicie depois de mudar as pastas ou as chaves pelo arquivo. Uma chave salva no cartão seguro passa a valer no app que está aberto.

## Testes

```bat
.venv\Scripts\python.exe -m pytest
```

## O que fica fora do GitHub

`.env`, `mcp.json`, `config.toml`, `data/`, `logs/` e `cerebro/` ficam na máquina. Ali estão as chaves, a caixa de e-mail, o banco das conversas e as notas privadas.

## Licença

Apache License 2.0. Veja [LICENSE](LICENSE).
