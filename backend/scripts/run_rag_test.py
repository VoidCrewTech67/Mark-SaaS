import sys
from pathlib import Path
import json

# Ensure backend package is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # Mark-SaaS/backend

from app.utils.optimizer import optimize_markdown, chunk_markdown_structured

# Path to uploads sample
sample = Path(__file__).resolve().parents[1] / "uploads" / "rag_pipeline_sample.txt"
if not sample.exists():
    print(f"ERROR: sample file not found: {sample}")
    sys.exit(2)

text = sample.read_text(encoding="utf-8")
opt_md = optimize_markdown(text)
chunks = chunk_markdown_structured(opt_md, None, None)

out = {
    "source_file": str(sample),
    "original_len": len(text),
    "optimized_len": len(opt_md),
    "chunk_count": len(chunks),
    "chunks": chunks,
}

print(json.dumps(out, indent=2, ensure_ascii=False))
