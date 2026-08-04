"""
Download Qwen3 model weights to user HF cache.
python backend/tests/download_models.py
"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

cache_dir = os.path.expanduser("~/.cache/huggingface/hub")

from huggingface_hub import snapshot_download

models = [
    "Qwen/Qwen3-Embedding-0.6B",
    "Qwen/Qwen3-Reranker-0.6B",
]

for name in models:
    print(f"\n=== {name} ===")
    t0 = time.time()
    try:
        path = snapshot_download(
            repo_id=name,
            cache_dir=cache_dir,
            resume_download=True,
        )
        print(f"OK: {path} ({time.time()-t0:.0f}s)")
    except Exception as e:
        print(f"FAILED [{time.time()-t0:.0f}s]: {e}")

print("\n=== DONE ===")
# Verify
for name in models:
    model_dir = os.path.join(cache_dir, f"models--{name.replace('/', '--')}")
    if os.path.isdir(model_dir):
        found = []
        for root, dirs, files in os.walk(model_dir):
            for f in files:
                if f.endswith('.safetensors'):
                    size_mb = os.path.getsize(os.path.join(root, f)) / 1_048_576
                    found.append(f"{f} ({size_mb:.0f}MB)")
        if found:
            print(f"{name}: {len(found)} weight files: {found[:5]}")
        else:
            print(f"{name}: NO weight files found in cache")
