# MarkItDown Converter

> Convert any document into AI-ready Markdown — with automatic OCR, token optimization, and smart chunking.

**Stack:** FastAPI (Python) · Next.js 16 · EasyOCR · Microsoft MarkItDown · Render · Vercel

---

## Repository Structure

```
mark/
├── backend/              # FastAPI backend
│   ├── app/
│   │   ├── api/          # Route handlers + DI
│   │   ├── core/         # Config + logging
│   │   ├── models/       # Pydantic request/response schemas
│   │   ├── services/     # Async service wrappers
│   │   ├── utils/        # Conversion engine (MarkItDown, OCR, optimizer, chunker, zip)
│   │   └── main.py       # FastAPI app factory + lifespan
│   ├── uploads/          # Runtime — temp uploaded files (gitignored)
│   ├── converted/        # Runtime — temp converted .md files (gitignored)
│   ├── requirements.txt
│   └── .env.example
│
├── frontend/             # Next.js frontend
│   ├── app/              # App Router pages + global CSS
│   ├── components/       # UI primitives + feature components
│   ├── hooks/            # useConversion, useHistory
│   ├── services/         # api.js (all fetch calls)
│   ├── lib/              # utils.js, clientZip.js
│   └── .env.local.example
│
├── render.yaml           # Render Blueprint (auto-detected at repo root)
├── DEPLOYMENT.md         # Step-by-step deploy guide
├── package.json          # Root workspace — `npm run dev` starts both servers
└── .gitignore
```

---

## Features

| Feature | Detail |
|---|---|
| **15+ file formats** | PDF, DOCX, PPTX, XLSX, HTML, TXT, CSV, JSON, XML, images, audio, EPUB |
| **Smart OCR** | EasyOCR with heuristic filtering (logos/icons skipped, meaningful text kept) |
| **Embedded Image OCR** | Extracts & OCRs every image embedded in a document |
| **SHA-256 cache** | Identical images OCR'd exactly once per server lifetime |
| **Token optimization** | Unicode normalization, deduplication, page-number stripping |
| **Smart chunking** | Heading-aware splits with configurable token limit + overlap |
| **ZIP export** | Download all chunks as a named ZIP |
| **Batch conversion** | Convert multiple files in one request |
| **TTL cleanup** | Files auto-deleted after 2 hours |

---

## Quick Start (Local)

```bash
# 1. Clone
git clone https://github.com/YOUR_USERNAME/markitdown.git
cd markitdown

# 2. Install root workspace tooling
npm install

# 3. Install Python backend deps
pip install -r backend/requirements.txt

# 4. Configure environment
cp backend/.env.example backend/.env
cp frontend/.env.local.example frontend/.env.local
# frontend/.env.local → NEXT_PUBLIC_API_URL=http://localhost:8000

# 5. Start both servers with one command
npm run dev
```

Open **http://localhost:3000** — API docs at **http://localhost:8000/docs**

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/health` | Liveness + capability check |
| `POST` | `/api/upload` | Upload a file (multipart/form-data) |
| `POST` | `/api/convert` | Convert a single uploaded file |
| `POST` | `/api/convert/batch` | Convert multiple uploaded files |
| `POST` | `/api/chunk` | Split Markdown into token-bounded chunks |
| `GET` | `/api/download/{id}` | Download the converted `.md` file |
| `GET` | `/api/download-zip/{id}` | Download chunks as a ZIP |
| `GET` | `/api/stats/{id}` | Get conversion statistics |

---

## Deploy

See **[DEPLOYMENT.md](./DEPLOYMENT.md)** for the full guide.

| Service | Platform | Config |
|---|---|---|
| Backend (FastAPI) | [Render](https://render.com) | `render.yaml` at repo root |
| Frontend (Next.js) | [Vercel](https://vercel.com) | `frontend/vercel.json` |

---

## Tech Stack

**Backend**
- [FastAPI](https://fastapi.tiangolo.com/) + [Uvicorn](https://www.uvicorn.org/) (async, production ASGI)
- [Microsoft MarkItDown](https://github.com/microsoft/markitdown) — core conversion engine
- [EasyOCR](https://github.com/JaidedAI/EasyOCR) — GPU/CPU-accelerated OCR
- [tiktoken](https://github.com/openai/tiktoken) — GPT-4-compatible token counting
- [PyMuPDF](https://pymupdf.readthedocs.io/) — PDF image extraction
- [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) — environment config

**Frontend**
- [Next.js 16](https://nextjs.org/) (App Router, JavaScript)
- [Tailwind CSS v4](https://tailwindcss.com/)
- [Lucide React](https://lucide.dev/) icons
- Custom dark design system (Vercel/Linear-inspired)
- Browser-native ZIP builder (no third-party library)
