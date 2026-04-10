#!/bin/bash
# Vision 2.0 Benchmark — Fase A3 Automática
# Roda benchmark em todos os 3 candidatos e gera relatório comparativo

set -e  # Exit on error

REPO_ROOT="E:/Seeker.Bot"
cd "$REPO_ROOT"

echo "=========================================="
echo "Vision 2.0 Benchmark — Fase A3"
echo "=========================================="
echo ""

# Array de modelos a testar
MODELS=("qwen2.5vl:7b" "qwen3-vl:8b" "minicpm-v")

# Função para rodar benchmark de um modelo
run_benchmark() {
    local model=$1
    echo ""
    echo ">>> Iniciando benchmark para: $model"
    echo ""

    # Valida que o modelo está instalado
    if ! ollama list | grep -q "^${model}\s"; then
        echo "❌ Modelo $model não encontrado. Pulando..."
        return 1
    fi

    # Roda benchmark (50 tasks por categoria para dados mais robustos)
    timeout 3600 python -m tests.vision_benchmark.runner --model "$model" --limit 50 || {
        echo "⚠️  Benchmark para $model completou com erro ou timeout"
        return 1
    }

    echo "✓ Benchmark completo para $model"
}

# Roda benchmark para cada modelo
for model in "${MODELS[@]}"; do
    run_benchmark "$model"
done

# Gera relatório comparativo
echo ""
echo "=========================================="
echo "Gerando relatório comparativo..."
echo "=========================================="
python -m tests.vision_benchmark.report --models "${MODELS[@]}" \
    --output "reports/vision_2_0_comparison.md"

echo ""
echo "✓ Relatório salvo em: reports/vision_2_0_comparison.md"
echo ""
echo "=========================================="
echo "Fase A3 COMPLETA"
echo "=========================================="
