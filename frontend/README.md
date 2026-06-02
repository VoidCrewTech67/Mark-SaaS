# MarkItDown Converter — Next.js Frontend

Modern, production-ready SaaS frontend for the MarkItDown conversion pipeline.

## Tech Stack

- **Next.js 16** (App Router, JavaScript)
- **Tailwind CSS v4**
- **Lucide React** icons
- **Custom design system** (Vercel/Linear-inspired dark theme)

## Features

- ✅ Drag-and-drop multi-file upload with staged file list
- ✅ Per-file conversion progress (uploading → converting → done)
- ✅ 4-tab result cards (Preview · Optimized · Chunks · Raw)
- ✅ Token optimization stats (before/after/saved/%)
- ✅ Smart chunking controls with overlap slider
- ✅ Chunk accordion viewer with per-chunk word count
- ✅ Copy-to-clipboard with feedback
- ✅ Download individual `.md` files
- ✅ Download chunk ZIP (client-side, no extra library)
- ✅ "Download All" bulk ZIP from in-memory markdown
- ✅ Session-only conversion history in sidebar
- ✅ Responsive — works on mobile and desktop
- ✅ Dark mode by default

## Quick Start

```bash
cd frontend
cp .env.local.example .env.local
# Set NEXT_PUBLIC_API_URL to your backend URL

npm install
npm run dev
```

App opens at: http://localhost:3000

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | FastAPI backend URL |

## Deployment on Vercel

1. Connect the repo on [Vercel](https://vercel.com).
2. Set **Root Directory** to `frontend`.
3. Add env var: `NEXT_PUBLIC_API_URL` → your Render backend URL.
4. Deploy — Vercel handles the rest.
