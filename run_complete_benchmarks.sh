#!/bin/bash
set -e

echo "════════════════════════════════════════════════════════"
echo "VISION 2.0 — COMPLETE BENCHMARK SUITE"
echo "════════════════════════════════════════════════════════"
echo ""

MODELS=(
    "qwen3.5:4b"
    "qwen2.5vl:7b"
    "qwen3-vl:8b"
    "minicpm-v"
)

echo "Modelos a testar:"
for model in "${MODELS[@]}"; do
    echo "  - $model"
done
echo ""

# Check which models are available
echo "Verificando disponibilidade..."
for model in "${MODELS[@]}"; do
    if ollama list | grep -q "$model"; then
        echo "  ✓ $model disponível"
    else
        echo "  ✗ $model NÃO disponível (pulando)"
    fi
done
echo ""

# Run benchmarks for available models
echo "Iniciando benchmarks..."
echo ""

for model in "${MODELS[@]}"; do
    # Check if model exists
    if ! ollama list 2>/dev/null | grep -q "$model"; then
        echo "⊘ Pulando $model (não disponível)"
        continue
    fi

    echo "════════════════════════════════════════════════════════"
    echo "BENCHMARK: $model"
    echo "════════════════════════════════════════════════════════"

    export VLM_MODEL="$model"

    # Run benchmark with 50 tasks (5 per category)
    python -m tests.vision_benchmark.runner \
        --model "$model" \
        --limit 50 \
        2>&1 | tee "benchmark_${model//:/_}.log"

    echo ""
done

echo "════════════════════════════════════════════════════════"
echo "TODOS OS BENCHMARKS CONCLUÍDOS"
echo "════════════════════════════════════════════════════════"
echo ""

# Generate comparison report
echo "Gerando relatório de comparação..."
python -m tests.vision_benchmark.report \
    --models qwen3.5:4b qwen2.5vl:7b qwen3-vl:8b minicpm-v \
    --output reports/vision_2_0_comparison.md

echo ""
echo "✓ Relatório salvo: reports/vision_2_0_comparison.md"
echo ""

# List all summaries
echo "Resumos gerados:"
ls -lh reports/summary_*.json 2>/dev/null | awk '{print "  " $9 " (" $5 ")"}'
echo ""

echo "🎉 BENCHMARK SUITE COMPLETO!"
