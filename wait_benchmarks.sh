#!/bin/bash
set -e

echo "Aguardando conclusão dos benchmarks..."
echo ""

# Aguarda modelo pull completar (máx 30 min)
echo "Aguardando models (timeout 30 min)..."
timeout 1800 bash -c '
while ! ollama list | grep -E "qwen2.5vl|minicpm-v" > /dev/null; do
  echo "  Modelos faltando... $(date +%H:%M:%S)"
  sleep 10
done
echo "✓ Modelos prontos: $(ollama list | grep -E "qwen|minicpm" | wc -l) encontrados"
'

echo ""
echo "Verificando benchmarks..."
for model in "qwen3-vl:8b" "qwen2.5vl:7b" "minicpm-v"; do
  model_slug=$(echo "$model" | sed 's/:/_/g')
  if [ -f "reports/summary_${model_slug}.json" ]; then
    echo "✓ $model benchmark completo"
  else
    echo "⏳ $model ainda rodando..."
  fi
done
