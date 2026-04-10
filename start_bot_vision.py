#!/usr/bin/env python3
import os
import sys
import subprocess
import time

# Set Vision 2.0 environment variables
os.environ["GEMINI_VLM_FALLBACK"] = "true"
os.environ["VLM_MODEL"] = "qwen3.5:4b"
os.environ["PYTHONIOENCODING"] = "utf-8"

print("[Vision2.0] Starting Seeker.Bot with Vision 2.0 enabled...")
print(f"  VLM_MODEL={os.environ['VLM_MODEL']}")
print(f"  GEMINI_VLM_FALLBACK={os.environ['GEMINI_VLM_FALLBACK']}")
print()

try:
    import src
    from src.main import main
    print("[Vision2.0] Seeker.Bot initialized successfully")
except Exception as e:
    print(f"[Vision2.0] Error: {e}")
    sys.exit(1)
