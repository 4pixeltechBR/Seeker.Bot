# Como configurar o Cowork como despachante do Seeker

## Passo 1 — Extraia os arquivos

Extraia o ZIP em `E:\Seeker.Bot\`. Você terá:
```
E:\Seeker.Bot\
├── SKILL.md          ← O Cowork lê isso automaticamente
├── README.md
├── docs\
├── src\
├── config\
├── scripts\
├── tests\
├── Downloads\        ← Zona de pouso dos arquivos do claude.ai
└── ...
```

## Passo 2 — Aponte o Cowork pra pasta

1. Abra o Claude Desktop
2. Mude pra modo **Cowork**
3. Clique em **"Work in a folder"** → selecione `E:\Seeker.Bot\`
4. O Cowork vai ler o SKILL.md automaticamente

## Passo 3 — Crie um Project (recomendado)

Com a feature Projects (lançada 20/mar/2026):
1. No Cowork, crie um novo Project chamado **"Seeker.Bot"**
2. Vincule à pasta `E:\Seeker.Bot\`
3. Isso mantém contexto persistente entre sessões

## Workflow diário

1. Eu (claude.ai) gero arquivos → você baixa
2. Joga na pasta `E:\Seeker.Bot\Downloads\`
3. Diz pro Cowork: **"despacha os downloads"**
4. Cowork classifica, move, e atualiza o changelog
5. Pra ver o status: **"status do seeker"** ou **"verifica o projeto"**

## Comandos do Cowork

| Comando | O que faz |
|---------|-----------|
| "despacha os downloads" | Classifica e move arquivos pendentes |
| "status do seeker" | Mostra status de cada módulo |
| "verifica o projeto" | Validação completa + imports + pendências |
| "mostra o changelog" | Últimas entradas do changelog |
