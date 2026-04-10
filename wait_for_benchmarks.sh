#!/bin/bash

echo "Aguardando conclusão dos benchmarks..."
echo ""

while true; do
    # Conta quantos summary files existem
    count=$(ls -1 reports/summary_*.json 2>/dev/null | wc -l)
    
    echo "[$(date +%H:%M:%S)] Progress: $count/4 modelos completados"
    
    if [ $count -eq 4 ]; then
        echo ""
        echo "✓ TODOS OS 4 MODELOS BENCHMARKED!"
        echo ""
        echo "Gerando relatório comparativo..."
        export PYTHONIOENCODING=utf-8
        python -m tests.vision_benchmark.report \
            --models qwen3.5:4b qwen3-vl:8b qwen2.5vl:7b minicpm-v \
            --output reports/vision_2_0_comparison_FINAL_4MODELS.md
        
        echo ""
        echo "Relatório gerado: reports/vision_2_0_comparison_FINAL_4MODELS.md"
        echo ""
        break
    fi
    
    sleep 30
done
