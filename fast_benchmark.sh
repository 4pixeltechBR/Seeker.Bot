#!/bin/bash
set -e

LIMIT=10  # Apenas 10 tasks por modelo para ter resultados rápidos

echo "=== FAST BENCHMARK MODE (LIMIT=$LIMIT) ==="
echo ""

# Inicia pulls em paralelo
echo "[$(date +%H:%M:%S)] Iniciando pulls dos modelos..."
(ollama pull qwen2.5vl:7b 2>&1 | grep -E "pulling|^[a-f0-9]" &)
(ollama pull minicpm-v 2>&1 | grep -E "pulling|^[a-f0-9]" &)
wait_pids=($!)

# Rodaaqui é um benchmark para qwen3-vl:8b que ja temos
if ollama list | grep -q "qwen3-vl:8b"; then
    echo "[$(date +%H:%M:%S)] Benchmark: qwen3-vl:8b..."
    export VLM_MODEL=qwen3-vl:8b
    python -m tests.vision_benchmark.runner --model "qwen3-vl:8b" --limit $LIMIT &
    BG_PIDS+=($!)
fi

# Aguarda modelo fique disponível
for i in {1..120}; do
    if ollama list | grep -q "qwen2.5vl:7b"; then
        echo "[$(date +%H:%M:%S)] Benchmark: qwen2.5vl:7b..."
        export VLM_MODEL=qwen2.5vl:7b
        python -m tests.vision_benchmark.runner --model "qwen2.5vl:7b" --limit $LIMIT &
        BG_PIDS+=($!)
        break
    fi
    sleep 5
done

for i in {1..120}; do
    if ollama list | grep -q "minicpm-v"; then
        echo "[$(date +%H:%M:%S)] Benchmark: minicpm-v..."
        export VLM_MODEL=minicpm-v
        python -m tests.vision_benchmark.runner --model "minicpm-v" --limit $LIMIT &
        BG_PIDS+=($!)
        break
    fi
    sleep 5
done

# Aguarda completion de todos
echo ""
echo "[$(date +%H:%M:%S)] Aguardando conclusão dos benchmarks..."
wait

echo ""
echo "[$(date +%H:%M:%S)] === COMPLETE ==="
echo ""
echo "Resultados gerados:"
ls -lh reports/summary_*.json 2>/dev/null | awk '{print $9, "(" $5 ")"}'
