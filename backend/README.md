# MarkItDown Converter — FastAPI Backend

Production-ready FastAPI backend for the MarkItDown document-to-Markdown conversion pipeline.

## File Structure

```
backend/
├── app/
│   ├── api/                          # API layer
│   │   ├── dependencies/
│   │   │   ├── __init__.py
│   │   │   └── services.py           # FastAPI DI providers
│   │   ├── routes/                   # Route handlers
│   │   │   ├── __init__.py
│   │   │   ├── health.py             # GET  /api/health
│   │   │   ├── upload.py             # POST /api/upload
│   │   │   ├── convert.py            # POST /api/convert, /api/convert/batch
│   │   │   ├── chunk.py              # POST /api/chunk
│   │   │   ├── download.py           # GET  /api/download/{id}, /api/download-zip/{id}
│   │   │   ├── stats.py              # GET  /api/stats/{id}
│   │   │   └── zip_upload.py
│   │   └── __init__.py
│   ├── services/                     # Async service layer
│   │   ├── __init__.py
│   │   ├── chunking_service.py
│   │   ├── cleanup_service.py
│   │   ├── conversion_service.py
│   │   ├── docling_service.py
│   │   ├── extractors.py
│   │   ├── ocr_service.py
│   │   ├── optimization_service.py
│   │   ├── research_paper_optimizer.py
│   │   ├── semantic_scoring.py
│   │   └── zip_service.py
│   ├── models/                       # Pydantic schemas
│   │   ├── __init__.py
│   │   ├── requests.py
│   │   └── responses.py
│   ├── optimizer/                    # Markdown optimization engine
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── config.py
│   │   ├── exceptions.py
│   │   ├── models.py
│   │   ├── pipeline.py
│   │   ├── pipeline_v2.py
│   │   ├── registry.py
│   │   ├── report.py
│   │   ├── validator.py
│   │   ├── passes/                   # Optimization passes
│   │   │   ├── __init__.py
│   │   │   ├── _example.py
│   │   │   ├── abbreviation_mining.py
│   │   │   ├── boilerplate_section.py
│   │   │   ├── citation.py
│   │   │   ├── content_boilerplate.py
│   │   │   ├── equation_preservation.py
│   │   │   ├── header_footer.py
│   │   │   ├── importance_aware.py
│   │   │   ├── ocr_cleanup.py
│   │   │   ├── paragraph_dedup.py
│   │   │   ├── reference_section.py
│   │   │   ├── semantic_dedup.py
│   │   │   ├── semantic_table_transform.py
│   │   │   └── table_compression.py
│   │   └── tests/                    # Optimizer tests
│   │       ├── __init__.py
│   │       ├── conftest.py
│   │       ├── test_*.py (comprehensive test suite)
│   │       └── ...
│   ├── utils/                        # Utility functions
│   │   ├── __init__.py
│   │   ├── converter.py
│   │   ├── doctype.py
│   │   ├── image_extractor.py
│   │   ├── ocr_handler.py
│   │   ├── optimizer.py
│   │   ├── token_counter.py
│   │   └── zip_handler.py
│   ├── core/                         # Core config
│   │   ├── __init__.py
│   │   ├── config.py
│   │   └── log_config.py
│   ├── __init__.py
│   └── main.py                       # FastAPI app factory
├── scripts/                          # Utility scripts
│   └── run_rag_test.py
├── tests/                            # Integration tests
│   └── test_semantic_scoring.py
├── uploads/                          # Temp uploaded files (UUID-named)
├── converted/                        # Temp converted .md files
├── .env
├── .env.example
├── requirements.txt
├── requirements-dev.txt
├── render.yaml
└── README.md
```

## Quick Start (Local)

```bash
# 1. Install dependencies
cd backend
pip install -r requirements.txt

# 2. Install poppler (required for pdf2image PDF fallback OCR)
#    Windows: https://github.com/oschwartz10612/poppler-windows/releases
#    macOS:   brew install poppler
#    Ubuntu:  sudo apt-get install -y poppler-utils

# 3. Copy env and configure
cp .env.example .env

# 4. Run
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

API docs available at: http://localhost:8000/docs

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Liveness + capability check |
| POST | `/api/upload` | Upload a file (multipart/form-data) |
| POST | `/api/convert` | Convert a single uploaded file |
| POST | `/api/convert/batch` | Convert multiple uploaded files |
| POST | `/api/chunk` | Split converted Markdown into chunks |
| GET | `/api/download/{id}` | Download the converted `.md` file |
| GET | `/api/download-zip/{id}` | Download chunks as a ZIP |
| GET | `/api/stats/{id}` | Get conversion statistics |

## Typical Workflow

```
POST /api/upload              → { file_id: "abc123" }
POST /api/convert             → { markdown, optimized_markdown, stats... }
POST /api/chunk               → { chunks: [...] }
GET  /api/download/{file_id}  → .md file download
GET  /api/download-zip/{id}   → chunks.zip download
```

## Environment Variables

See `.env.example` for all configurable settings.

Key variables for production:

| Variable | Default | Description |
|---|---|---|
| `ALLOWED_ORIGINS` | `http://localhost:3000` | CORS — set to your Vercel URL |
| `MAX_UPLOAD_SIZE_MB` | `150` | Per-file upload limit |
| `FILE_TTL_SECONDS` | `7200` | How long files are kept (2 hours) |
| `OCR_WARM_UP_ON_STARTUP` | `true` | Pre-load EasyOCR on startup |
| `DEBUG` | `false` | Enable debug logging |

## Deployment on Render

1. Push the repo to GitHub.
2. Create a new **Web Service** on [Render](https://render.com), connect the repo.
3. Render auto-reads `render.yaml` — no manual configuration needed.
4. Set `ALLOWED_ORIGINS` to your Vercel deployment URL in the Render dashboard.
5. The build command installs `poppler-utils` automatically.

**Recommended plan:** `Starter` (512 MB) for light usage, `Standard` (2 GB) for comfortable EasyOCR operation.

## Notes

- **No database required** — all state is in-memory with TTL-based cleanup.
- **EasyOCR warm-up** — the first startup loads ~100 MB of model weights. Render keeps the process warm between requests so subsequent cold starts are rare.
- **Single worker** — `--workers 1` is intentional: EasyOCR's singleton reader is not safe to share across OS processes. Scale horizontally with multiple Render instances if needed.
