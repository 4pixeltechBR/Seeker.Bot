#!/bin/bash

MODELS=("qwen3.5:4b" "qwen2.5vl:7b" "qwen3-vl:8b" "minicpm-v")
TIMEOUT=3600  # 1 hora

check_ready() {
    all_ready=true
    for model in "${MODELS[@]}"; do
        slug=$(echo "$model" | sed 's/:/_/g')
        if [ ! -f "reports/summary_${slug}.json" ]; then
            all_ready=false
            break
        fi
    done
    echo "$all_ready"
}

echo "Aguardando todos os benchmarks (timeout: ${TIMEOUT}s)..."
echo ""

START_TIME=$(date +%s)
while true; do
    ELAPSED=$(($(date +%s) - START_TIME))
    
    if [ "$(check_ready)" = "true" ]; then
        echo "✅ Todos os benchmarks completos!"
        echo ""
        echo "Executando análise de decisão Phase A4..."
        python analyze_a4_decision.py
        exit 0
    fi
    
    if [ $ELAPSED -gt $TIMEOUT ]; then
        echo "❌ Timeout aguardando benchmarks"
        echo "Rodando análise com dados parciais..."
        python analyze_a4_decision.py
        exit 1
    fi
    
    REMAINING=$((TIMEOUT - ELAPSED))
    echo "[$(date +%H:%M:%S)] Aguardando... (${REMAINING}s restantes)"
    sleep 10
done
