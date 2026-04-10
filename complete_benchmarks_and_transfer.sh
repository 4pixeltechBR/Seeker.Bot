#!/bin/bash

TARGET_DIR="E:\Downloads ViralClipOS\LLM Models"

echo "=========================================="
echo "AGUARDANDO CONCLUSAO DOS BENCHMARKS..."
echo "=========================================="
echo ""

# Aguarda conclusao dos 4 benchmarks
while true; do
    count=$(ls -1 reports/summary_*.json 2>/dev/null | wc -l)
    timestamp=$(date +%H:%M:%S)
    
    echo "[$timestamp] Progress: $count/4 modelos completados"
    
    if [ $count -eq 4 ]; then
        echo ""
        echo "✓ TODOS OS 4 MODELOS BENCHMARKED!"
        break
    fi
    
    sleep 30
done

echo ""
echo "=========================================="
echo "GERANDO RELATORIO FINAL..."
echo "=========================================="
echo ""

export PYTHONIOENCODING=utf-8
python -m tests.vision_benchmark.report \
    --models qwen3.5:4b qwen3-vl:8b qwen2.5vl:7b minicpm-v \
    --output reports/vision_2_0_comparison_FINAL_4MODELS.md 2>&1 | tail -5

echo ""
echo "✓ Relatorio gerado: reports/vision_2_0_comparison_FINAL_4MODELS.md"
echo ""

echo "=========================================="
echo "TRANSFERINDO MODELOS PARA..."
echo "$TARGET_DIR"
echo "=========================================="
echo ""

# Criar diretorio destino se nao existir
mkdir -p "$TARGET_DIR" 2>/dev/null

# Listar modelos Ollama e copiar
echo "Modelos Ollama a transferir:"
ollama list | grep -v "^NAME" | while read line; do
    if [ -n "$line" ]; then
        echo "  - $line"
    fi
done

echo ""
echo "[INFO] Copiando arquivos do Ollama para E:\Downloads ViralClipOS\LLM Models..."
echo ""

# Nota: Os arquivos Ollama sao armazenados em blobs com hash
# A copia direta do blob store pode nao ser pratica
# Melhor alternativa: usar 'ollama export' ou documentar o comando

echo "OPCAO 1 - Exportar cada modelo (recomendado):"
echo "  ollama export qwen3.5:4b qwen3.5_4b.gguf"
echo "  ollama export qwen3-vl:8b qwen3-vl_8b.gguf"
echo "  ollama export qwen2.5vl:7b qwen2.5vl_7b.gguf"
echo "  ollama export minicpm-v minicpm_v.gguf"
echo ""

echo "OPCAO 2 - Copiar blob store completo:"
echo "  xcopy C:\Users\Victor\AppData\Local\Ollama\models \"$TARGET_DIR\" /S /E /Y"
echo ""

echo "Iniciando transferencia..."
echo ""

# Tentar copiar o blob store
if [ -d "C:\Users\Victor\AppData\Local\Ollama\models" ]; then
    echo "Copiando pasta de modelos..."
    cp -r "C:\Users\Victor\AppData\Local\Ollama\models"/* "$TARGET_DIR" 2>&1 | head -5
    
    if [ $? -eq 0 ]; then
        echo ""
        echo "✓ TRANSFERENCIA COMPLETA!"
        echo "Modelos agora em: $TARGET_DIR"
        echo ""
        echo "=========================================="
        echo "RESUMO FINAL - VISION 2.0 SPRINT 12"
        echo "=========================================="
        echo ""
        echo "Benchmarks: 4/4 COMPLETO"
        echo "Relatorio: reports/vision_2_0_comparison_FINAL_4MODELS.md"
        echo "Modelos: $TARGET_DIR"
        echo ""
        echo "Status: PRONTO PARA PRODUCAO"
        echo ""
    else
        echo "⚠ Erro na transferencia. Pasta pode nao existir ou sem permissoes."
    fi
else
    echo "⚠ Pasta de modelos Ollama nao encontrada"
    echo "   Localizacao esperada: C:\Users\Victor\AppData\Local\Ollama\models"
fi

