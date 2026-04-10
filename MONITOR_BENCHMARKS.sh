#!/bin/bash
# Monitor Vision 2.0 Benchmarks (Fase A3)

echo "=========================================="
echo "Vision 2.0 Benchmark Monitor"
echo "=========================================="
echo ""
echo "Current time: $(date)"
echo ""

# Check model availability
echo "=== Models Installed ==="
ollama list | grep -E "(qwen3.5|qwen2.5vl|qwen3-vl|minicpm)"
echo ""

# Check benchmark results
echo "=== Benchmark Results Available ==="
if [ -d "reports/" ]; then
    ls -lh reports/summary_*.json 2>/dev/null | awk '{print $9, "-", $5}' || echo "No summaries yet"
fi
echo ""

# Show report if available
echo "=== Comparison Report ==="
if [ -f "reports/vision_2_0_comparison.md" ]; then
    echo "Report found! Preview:"
    head -50 reports/vision_2_0_comparison.md
else
    echo "Report not yet generated. Waiting for benchmarks to complete..."
fi
echo ""

# Count tasks in reports
echo "=== Progress ==="
total=0
for f in reports/results_*.json; do
    if [ -f "$f" ]; then
        count=$(grep -c "task_id" "$f" 2>/dev/null || echo 0)
        model=$(basename "$f" | sed 's/results_//; s/.json//')
        echo "  $model: $count tasks completed"
        total=$((total + count))
    fi
done
echo "  Total: $total tasks"
echo ""

echo "Next: Check back in 30 minutes, or run:"
echo "  python -m tests.vision_benchmark.report --models qwen3.5:4b qwen2.5vl:7b qwen3-vl:8b minicpm-v"
