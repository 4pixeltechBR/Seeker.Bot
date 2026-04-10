# Vision 2.0 — Network Issue & Workaround

## Problem

Ollama registry DNS lookup failed:
```
Error: max retries exceeded: dial tcp: lookup dd20bb891979d25aebc8bec07b2b3bbc.r2.cloudflarestorage.com: no such host
```

This blocks pulling models (qwen2.5vl:7b, qwen3-vl:8b, minicpm-v) from Ollama registry.

**Possible causes:**
- Temporary Ollama registry downtime
- Network connectivity issue
- ISP DNS blocking
- Cloudflare R2 storage unavailable

## Workaround: Use Local GGUFs

You already have **Qwen2.5-VL-7B GGUF** locally at:
```
E:\Downloads ViralClipOS\LLM Models\qwen2.5-vl-7b-instruct-q4_k_m.gguf (4.68 GB)
```

### Option 1: Retry with Ollama (Simplest)

```bash
# Wait 5-10 minutes and try again
ollama pull qwen2.5vl:7b
ollama pull qwen3-vl:8b
ollama pull minicpm-v
```

**Status:** Trying now in background. Will complete eventually if network recovers.

### Option 2: Use Local GGUF with llama-cpp-python (Faster Alternative)

If network doesn't recover, can use local GGUF file directly:

```python
# Pseudo-code for adapter
from llama_cpp import Llama

model = Llama(
    model_path="E:/Downloads ViralClipOS/LLM Models/qwen2.5-vl-7b-instruct-q4_k_m.gguf",
    n_gpu_layers=50,  # GPU acceleration
    vision_capable=True,
)

# Same API as VLMClient
response = model.create_chat_completion(
    messages=[...],
    images=[...],  # for multimodal
)
```

**Requires:** `pip install llama-cpp-python`

**Advantage:** No network, full control, fast local inference

**Disadvantage:** Need new VLMClient adapter class

### Option 3: Use Ollama HTTP with Timeout Retry

```bash
#!/bin/bash
MAX_RETRIES=3
RETRY_DELAY=60  # seconds

for model in qwen2.5vl:7b qwen3-vl:8b minicpm-v; do
    for i in $(seq 1 $MAX_RETRIES); do
        echo "Attempt $i for $model..."
        ollama pull "$model" && break
        if [ $i -lt $MAX_RETRIES ]; then
            echo "Retrying in ${RETRY_DELAY}s..."
            sleep $RETRY_DELAY
        fi
    done
done
```

---

## Recommended Action Now

1. **Wait 5-10 min for network to stabilize**, then check:
   ```bash
   ollama list
   # If qwen3-vl:8b, qwen2.5vl:7b, minicpm-v appear → proceed with benchmark
   ```

2. **If still failing after 15 min:**
   - Option 2: Create llama-cpp adapter + use local GGUF
   - Takes 1-2h extra implementation time
   - But guarantees you can run A3 benchmark

3. **If network fully down:**
   - Fall back to using only local Qwen3.5-4B baseline for now
   - Reschedule model upgrades when network recovers

---

## Current Status

- qwen3.5:4b → ✅ Already installed (3.4 GB)
- qwen2.5vl:7b → ⏳ Attempting pull (network issue)
- qwen3-vl:8b → ⏳ Attempting pull (network issue, trying again now)
- minicpm-v → ❌ Failed (network issue)

**Session Timeline:**
- If network recovers in 5-10 min: Full A3 benchmark in 2-3h
- If network down indefinitely: Need adapter (1-2h) + 2-3h benchmark = 3-5h total

---

## Files Modified for Workaround

If you choose Option 2 (local GGUF), will need:
- `src/skills/vision/vlm_client_gguf.py` — llama-cpp adapter
- Update benchmark runner to detect GGUF vs Ollama
- Requires: `pip install llama-cpp-python[cuda]`

---

## Decision Point

What's your preference if network doesn't recover in 10 min?

A) **Keep waiting** (Ollama might recover, best for reproduction)
B) **Use local GGUF adapter** (Faster, but requires code change)
C) **Postpone A3 to next session** (Let network stabilize, safest)
