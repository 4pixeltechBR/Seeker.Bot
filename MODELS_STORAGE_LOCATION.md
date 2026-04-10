# Localizacao dos Modelos Ollama Baixados

## Pasta Padrao (Windows)

Todos os 4 modelos estao armazenados em:

```
C:\Users\Victor\AppData\Local\Ollama\models\
```

Especificamente:
```
C:\Users\Victor\AppData\Local\Ollama\models\blobs\
```

## Modelos Instalados

| Modelo | Tamanho | ID |
|--------|---------|-----|
| qwen3.5:4b | 3.4 GB | 2a654d98e6fb |
| qwen3-vl:8b | 6.1 GB | 901cae732162 |
| qwen2.5vl:7b | 6.0 GB | 5ced39dfa4ba |
| minicpm-v | 5.5 GB | c92bfad01205 |

**TOTAL: ~21 GB de espaco em disco**

## Como Acessar

1. Abra **File Explorer**
2. Cole na barra de endereco:
   ```
   %APPDATA%\Local\Ollama\models
   ```
3. Pressione **Enter**

## Gerenciamento

Para **remover um modelo**:
```bash
ollama rm qwen2.5vl:7b
```

Para **liberar espaco**:
```bash
ollama prune
```

## Nota

Os modelos sao gerenciados pelo Ollama automaticamente. 
Nao recomenda-se mover manualmente os arquivos do blob store.
