#!/bin/bash
set -e

cd "E:/Seeker.Bot"

echo "════════════════════════════════════════════════════════════════════"
echo "VISION 2.0 SPRINT 12 — FINAL BENCHMARK SUITE"
echo "════════════════════════════════════════════════════════════════════"
echo ""
echo "Data: $(date)"
echo ""

# Verify all 4 models are available
echo "Verificando disponibilidade de modelos..."
echo ""

MISSING=()
for model in "qwen3.5:4b" "qwen3-vl:8b" "qwen2.5vl:7b" "minicpm-v"; do
    if ollama list 2>/dev/null | grep -q "$model"; then
        echo "  ✓ $model"
    else
        echo "  ✗ $model (NÃO DISPONÍVEL)"
        MISSING+=("$model")
    fi
done

echo ""

if [ ${#MISSING[@]} -gt 0 ]; then
    echo "❌ Modelos faltando:"
    for model in "${MISSING[@]}"; do
        echo "   - $model"
    done
    exit 1
fi

echo "✓ Todos os 4 modelos prontos!"
echo ""

# Run benchmarks
echo "════════════════════════════════════════════════════════════════════"
echo "RODANDO BENCHMARKS (5 tasks por modelo = 20 tasks totais)"
echo "════════════════════════════════════════════════════════════════════"
echo ""

MODELS=(
    "qwen3.5:4b"
    "qwen3-vl:8b"
    "qwen2.5vl:7b"
    "minicpm-v"
)

for i in "${!MODELS[@]}"; do
    model="${MODELS[$i]}"
    num=$((i + 1))

    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "BENCHMARK $num/4: $model"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""

    export VLM_MODEL="$model"

    python -m tests.vision_benchmark.runner \
        --model "$model" \
        --limit 50 \
        2>&1

    echo "✓ Benchmark $num concluído"
done

echo ""
echo "════════════════════════════════════════════════════════════════════"
echo "TODOS OS BENCHMARKS CONCLUÍDOS!"
echo "════════════════════════════════════════════════════════════════════"
echo ""

# Generate comparison report
echo "Gerando relatório de comparação..."
python -m tests.vision_benchmark.report \
    --models qwen3.5:4b qwen3-vl:8b qwen2.5vl:7b minicpm-v \
    --output reports/vision_2_0_comparison_final.md 2>&1 || true

echo ""
echo "✓ Relatório: reports/vision_2_0_comparison_final.md"
echo ""

# List all summaries
echo "Summaries gerados:"
ls -lh reports/summary_*.json 2>/dev/null | awk '{print "  " $9 " (" $5 ")"}'

echo ""
echo "════════════════════════════════════════════════════════════════════"
echo "🎉 SPRINT 12 VISION 2.0 COMPLETO COM TODOS OS 4 MODELOS!"
echo "════════════════════════════════════════════════════════════════════"
