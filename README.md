# Mark-SaaS

An open-source document-to-Markdown pipeline for LLM and RAG applications.

---

## What it does

Takes raw documents (PDFs, DOCX, PPTX, and others), converts them to clean Markdown, runs a multi-pass token optimization pipeline, scores how much meaning was preserved, and returns both the raw and optimized outputs with full analytics.

The main reduction is achieved by removing boilerplate, headers, footers, inline citations, reference sections, and duplicate paragraphs. The system then validates the output using embedding-based semantic scoring to confirm meaning was not lost.

---

## Extraction Modes

Document routing is determined by the `document_type` field sent in the conversion request.

| Document Type | Extractor | Notes |
|---|---|---|
| `general_document` | MarkItDown | Default. Handles PDF, DOCX, PPTX, XLSX, HTML, and more. Includes an EasyOCR fallback for image-heavy or scanned PDFs. |
| `research_paper` | Docling | Used for academic papers and structured technical documents. Falls back to MarkItDown if Docling is unavailable or fails. |

Embedded images within documents are handled separately. EasyOCR is run on embedded images when the OCR mode is set to `Smart (Recommended)` or higher.

---

## Optimization Modes

The optimizer supports four modes, selected via the `optimization_mode` field.

| Mode | Passes Run |
|---|---|
| `safe` | Equation protection, OCR artifact cleanup, header/footer detection |
| `balanced` | Safe passes + reference section removal, boilerplate removal, citation removal, paragraph deduplication |
| `aggressive` | Balanced passes + table compression, semantic table transform, abbreviation mining, semantic deduplication, importance-aware filtering |
| `rag` | Retrieval pipeline — `balanced` passes + structured chunking (chunk_id, section, token/word/char counts). Returns JSON, not markdown. Frontend renders a dedicated dashboard + chunk cards (no Preview/Optimized/Raw tabs). Primary export is `<name>.rag.json`, directly consumable by ChromaDB, Pinecone, Qdrant, Weaviate, LangChain, LlamaIndex. |

Default mode is `balanced`.

---

## Evaluation Scores

After every optimization run, the service computes three scores by comparing the original markdown to the optimized markdown.

**Semantic Preservation** — Uses `sentence-transformers/all-MiniLM-L6-v2` to embed overlapping sentence chunks from both documents and computes bidirectional recall. Falls back to bag-of-words cosine similarity if the model is unavailable.

**Context Preservation** — A weighted composite of six structural sub-metrics:

| Sub-metric | Weight | What it checks |
|---|---|---|
| Section score | 25% | Markdown headings (`#`, `##`, `###`) retained |
| Table score | 20% | Table rows retained |
| Numeric score | 20% | Numbers and measurements retained |
| Code score | 10% | Fenced code blocks retained |
| Image score | 10% | Image references retained |
| Entity score | 15% | Named entities (proper nouns, acronyms, versions) retained |

**Overall Preservation** — Harmonic mean of the semantic and context scores.

Scores are labeled: `Excellent` (≥ 98%), `Good` (≥ 95%), `Moderate` (≥ 90%), `Significant Loss` (< 90%).

---

## API Endpoints

All routes are mounted under `/api`. Interactive docs at `/docs` and `/redoc` when the server is running.

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/health` | Health check |
| `POST` | `/api/upload` | Upload a single file. Returns a `file_id`. Max 150 MB. |
| `POST` | `/api/upload-zip` | Upload a ZIP. Extracts, converts each file independently. Max 500 MB, max 1000 files. |
| `POST` | `/api/convert` | Convert an uploaded file by `file_id`. Runs extraction → optimization → scoring. |
| `POST` | `/api/convert/batch` | Convert multiple `file_id`s sequentially. |
| `POST` | `/api/chunk` | Split a converted document into token-bounded chunks. Must be called after `/api/convert`. |
| `GET` | `/api/download/{file_id}` | Download the optimized markdown for a converted file. |
| `GET` | `/api/download-zip/{file_id}` | Download all chunks as a ZIP archive. |
| `GET` | `/api/stats/{file_id}` | Retrieve optimization statistics for a converted file. |

Files are held in memory for 2 hours (configurable) and cleaned up by a background task.

---

## Project Structure

```text
Mark-SaaS/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   ├── dependencies/       # FastAPI dependency injectors (services, registries)
│   │   │   └── routes/             # health.py, upload.py, convert.py, chunk.py,
│   │   │                           # download.py, stats.py, zip_upload.py
│   │   ├── core/
│   │   │   ├── config.py           # pydantic-settings app configuration
│   │   │   └── log_config.py       # logging setup
│   │   ├── models/                 # Pydantic request and response schemas
│   │   ├── optimizer/
│   │   │   ├── passes/             # Individual optimization pass implementations
│   │   │   ├── base.py             # OptimizerPass abstract base class
│   │   │   ├── config.py           # PipelineConfig
│   │   │   ├── pipeline.py         # PipelineExecutor
│   │   │   ├── pipeline_v2.py
│   │   │   ├── registry.py         # PassRegistry (auto-discovers passes)
│   │   │   ├── report.py           # OptimizationReportGenerator
│   │   │   └── validator.py
│   │   ├── services/
│   │   │   ├── chunking_service.py        # Token-bounded chunking
│   │   │   ├── cleanup_service.py         # Background TTL-based file cleanup
│   │   │   ├── conversion_service.py      # Orchestrates extractor → optimizer
│   │   │   ├── docling_service.py         # Docling wrapper
│   │   │   ├── extractors.py              # MarkItDownExtractor, DoclingExtractor, factory
│   │   │   ├── ocr_service.py             # EasyOCR singleton
│   │   │   ├── optimization_service.py    # Mode-aware pipeline runner + scoring
│   │   │   ├── research_paper_optimizer.py
│   │   │   ├── semantic_scoring.py        # Three-score evaluation service
│   │   │   └── zip_service.py
│   │   └── utils/                  # FileConverter, token counter, OCR handler
│   ├── tests/
│   │   └── test_semantic_scoring.py
│   ├── .env.example
│   └── requirements.txt
├── frontend/
│   ├── app/
│   │   ├── page.js                 # Main dashboard
│   │   ├── layout.js
│   │   └── globals.css
│   ├── components/
│   │   ├── ChunkViewer.jsx
│   │   ├── ConversionProgress.jsx
│   │   ├── Header.jsx
│   │   ├── MarkdownPreview.jsx
│   │   ├── Navbar.jsx
│   │   ├── ResultCard.jsx
│   │   ├── SessionHistory.jsx
│   │   ├── SettingsPanel.jsx
│   │   ├── Sidebar.jsx
│   │   ├── StatsDisplay.jsx
│   │   ├── UploadZone.jsx
│   │   ├── converter/
│   │   ├── layout/
│   │   ├── sections/
│   │   └── ui/
│   ├── hooks/
│   │   ├── useConversion.js        # Upload → convert → chunk state machine
│   │   └── useHistory.js
│   ├── services/                   # API client wrappers
│   ├── .env.local.example
│   └── package.json
├── render.yaml                     # Render deployment blueprint (backend)
└── DEPLOYMENT.md
```

---

## Tech Stack

Derived directly from `requirements.txt` and `package.json`.

**Backend**

| Package | Purpose |
|---|---|
| `fastapi >= 0.115.0` | Web framework |
| `uvicorn[standard] >= 0.30.0` | ASGI server |
| `pydantic >= 2.7.0` + `pydantic-settings >= 2.3.0` | Settings and request/response validation |
| `markitdown[all] >= 0.1.0` | General document extraction |
| `easyocr >= 1.7.1` | OCR for embedded images and scanned PDFs |
| `sentence-transformers >= 3.0.0` | Semantic embedding scoring (`all-MiniLM-L6-v2`) |
| `scikit-learn >= 1.4.0` | Cosine similarity utilities |
| `tiktoken >= 0.7.0` | Token counting |
| `pymupdf >= 1.24.0` | PDF page rendering for OCR |
| `pdf2image >= 1.16.3` | PDF to image conversion |
| `python-docx >= 1.1.0` | DOCX handling |
| `Pillow >= 10.0.0` | Image processing |
| `aiofiles >= 23.2.1` | Async file I/O |
| `python-multipart >= 0.0.9` | Multipart form upload |

Docling is a separate dependency not listed in `requirements.txt`. The `DoclingExtractor` imports it lazily and falls back to MarkItDown if it is not installed.

**Frontend**

| Package | Purpose |
|---|---|
| `next 16.2.7` | React framework |
| `react 19.2.4` | UI library |
| `framer-motion ^12.40.0` | Animations |
| `lucide-react ^1.17.0` | Icons |
| `tailwindcss ^4` | Styling |
| `clsx ^2.1.1` + `tailwind-merge ^3.6.0` | Class name utilities |

---

## Installation

### Backend

```bash
git clone https://github.com/VoidCrewTech67/Mark-SaaS.git
cd Mark-SaaS/backend

python -m venv venv
# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt

cp .env.example .env
# Edit .env if needed (defaults work for local dev)

uvicorn app.main:app --reload --port 8000
```

The API will be available at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

System dependencies required by `easyocr` and `pdf2image`:
- **Linux/macOS:** `poppler-utils`, `libgl1-mesa-glx`, `libglib2.0-0`
- **Windows:** Poppler binaries must be on `PATH`

### Frontend

```bash
cd Mark-SaaS/frontend

cp .env.local.example .env.local
# NEXT_PUBLIC_API_URL defaults to http://localhost:8000

npm install
npm run dev
```

The UI runs at `http://localhost:3000`.

---

## Environment Variables

**Backend** (`.env` in `backend/`):

| Variable | Default | Description |
|---|---|---|
| `PORT` | `8000` | Server port |
| `HOST` | `0.0.0.0` | Server host |
| `DEBUG` | `false` | Enable debug logging |
| `UPLOAD_DIR` | `uploads` | Directory for uploaded files |
| `CONVERTED_DIR` | `converted` | Directory for converted files |
| `MAX_UPLOAD_SIZE_MB` | `150` | Max file size per upload |
| `ALLOWED_ORIGINS` | `http://localhost:3000,...` | Comma-separated CORS origins |
| `CLEANUP_INTERVAL_SECONDS` | `1800` | How often the cleanup task runs |
| `FILE_TTL_SECONDS` | `7200` | How long files are kept (2 hours) |
| `OCR_WARM_UP_ON_STARTUP` | `true` | Pre-load EasyOCR weights on startup |
| `OCR_IMAGE_TIMEOUT_S` | `60` | Timeout per image OCR call |
| `MARKITDOWN_TIMEOUT_S` | `120` | Timeout per MarkItDown conversion |

**Frontend** (`.env.local` in `frontend/`):

| Variable | Default | Description |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | Backend base URL |

---

## Deployment

The repository includes `render.yaml` for deploying the backend to [Render](https://render.com).

The build command installs system dependencies (`poppler-utils`, `libgl1-mesa-glx`, `libglib2.0-0`) and the Python packages. The start command uses `--workers 1` because EasyOCR's model is a singleton not safe for multi-process sharing.

The frontend is deployable to Vercel using standard Next.js defaults. Set `NEXT_PUBLIC_API_URL` to your Render backend URL, and set `ALLOWED_ORIGINS` in the Render environment to your Vercel URL.

---

## Testing

```bash
cd backend
pytest tests/
```

The test suite currently covers `semantic_scoring.py`.

---

## Current Limitations

- **Legacy PDFs with no text layer:** Some older PDFs contain neither selectable text nor image layers that EasyOCR can process. These files currently return empty or near-empty output and are unsupported.
- **Scanned documents with low DPI:** Poor scan quality results in degraded OCR accuracy.
- **Docling as optional dependency:** Docling is not in `requirements.txt`. If it is not installed, all `research_paper` requests silently fall back to MarkItDown.
- **Single-worker constraint:** The EasyOCR singleton prevents horizontal scaling within a single process. `--workers 1` is required on the backend.
- **In-memory file registry:** Upload and result registries are held in process memory. Restarting the server clears all pending conversions.

---

## Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md) for setup instructions, branch naming, commit conventions, and pull request guidelines.

---

## License

MIT

---

## Acknowledgements

- [Microsoft MarkItDown](https://github.com/microsoft/markitdown)
- [IBM Docling](https://github.com/DS4SD/docling)
- [EasyOCR](https://github.com/JaidedAI/EasyOCR)
- [Sentence-Transformers](https://sbert.net/)
