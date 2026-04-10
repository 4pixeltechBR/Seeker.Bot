#!/bin/bash

# Força execução de benchmarks para modelos disponíveis
# E aguarda pulls dos outros

echo "=== Vision 2.0 Phase A3 — Benchmark Parallel ==="
echo ""

# Função para rodar benchmark com logging
run_benchmark() {
    local model=$1
    echo "[$(date +%H:%M:%S)] Iniciando: $model"
    
    export VLM_MODEL="$model"
    timeout 1800 python -m tests.vision_benchmark.runner \
        --model "$model" \
        --limit 50 \
        2>&1 | grep -E "^(Benchmark|Error|Completed|Task)" || true
    
    echo "[$(date +%H:%M:%S)] Concluído: $model"
}

# 1. Qwen3-VL-8B (já disponível)
if ollama list | grep -q "qwen3-vl:8b"; then
    echo "Qwen3-VL-8B disponível, iniciando..."
    run_benchmark "qwen3-vl:8b" &
    PID_VL8B=$!
fi

# 2. Aguarda e pull dos outros modelos
echo ""
echo "Aguardando pulls dos modelos..."
for i in {1..120}; do
    if ollama list | grep -q "qwen2.5vl:7b"; then
        echo "[$(date +%H:%M:%S)] Qwen2.5-VL-7B pronto!"
        run_benchmark "qwen2.5vl:7b" &
        break
    fi
    sleep 5
done &

for i in {1..120}; do
    if ollama list | grep -q "minicpm-v"; then
        echo "[$(date +%H:%M:%S)] MiniCPM-V pronto!"
        run_benchmark "minicpm-v" &
        break
    fi
    sleep 5
done &

# Aguarda todas as tarefas
wait

echo ""
echo "=== Todos os benchmarks completos ==="
ls -lh reports/summary_*.json | awk '{print $9, $5}'
