#!/bin/bash
set -e

cd "E:/Seeker.Bot"

echo "════════════════════════════════════════════════════════════════════"
echo "VISION 2.0 SPRINT 12 — BENCHMARK COMPLETO 4/4 MODELOS"
echo "════════════════════════════════════════════════════════════════════"
echo ""
echo "Data: $(date)"
echo ""

# Verify all 4 models are available
echo "Verificando disponibilidade de modelos..."
echo ""

MODELS=(
    "qwen3.5:4b"
    "qwen3-vl:8b"
    "qwen2.5vl:7b"
    "minicpm-v"
)

for model in "${MODELS[@]}"; do
    if ollama list 2>/dev/null | grep -q "$model"; then
        echo "  ✓ $model"
    else
        echo "  ✗ $model (NÃO DISPONÍVEL)"
        exit 1
    fi
done

echo ""
echo "✓ Todos os 4 modelos prontos!"
echo ""

# Run benchmarks for each model
echo "════════════════════════════════════════════════════════════════════"
echo "EXECUTANDO BENCHMARKS (5 tasks por modelo = 20 tasks totais)"
echo "════════════════════════════════════════════════════════════════════"
echo ""

for i in "${!MODELS[@]}"; do
    model="${MODELS[$i]}"
    num=$((i + 1))

    echo ""
    echo "────────────────────────────────────────────────────────────────────"
    echo "BENCHMARK $num/4: $model"
    echo "────────────────────────────────────────────────────────────────────"
    echo ""

    export VLM_MODEL="$model"
    export PYTHONIOENCODING=utf-8

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
export PYTHONIOENCODING=utf-8
python -m tests.vision_benchmark.report \
    --models qwen3.5:4b qwen3-vl:8b qwen2.5vl:7b minicpm-v \
    --output reports/vision_2_0_comparison_FINAL_4MODELS.md 2>&1 || true

echo ""
echo "✓ Relatório: reports/vision_2_0_comparison_FINAL_4MODELS.md"
echo ""

# List all summaries
echo "Summaries gerados:"
ls -lh reports/summary_*.json 2>/dev/null | awk '{print "  " $9 " (" $5 ")"}'

echo ""
echo "════════════════════════════════════════════════════════════════════"
echo "SPRINT 12 COMPLETO COM TODOS OS 4 MODELOS!"
echo "════════════════════════════════════════════════════════════════════"
