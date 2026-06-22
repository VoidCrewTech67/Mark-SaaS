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

## File Structure

```
frontend/
├── app/                          # Next.js App Router
│   ├── layout.js                 # Root layout + global styles
│   ├── page.js                   # Home page
│   ├── globals.css               # Global Tailwind styles
│   ├── favicon.ico
│   └── docs/
│       └── page.js               # Documentation page
├── components/                   # React components
│   ├── Header.jsx
│   ├── Navbar.jsx
│   ├── Sidebar.jsx
│   ├── UploadZone.jsx
│   ├── ChunkViewer.jsx
│   ├── MarkdownPreview.jsx
│   ├── ResultCard.jsx
│   ├── StatsDisplay.jsx
│   ├── SettingsPanel.jsx
│   ├── ConversionProgress.jsx
│   ├── SessionHistory.jsx
│   ├── converter/                # Converter subcomponents
│   │   ├── DropZone.jsx
│   │   ├── PremiumResultCard.jsx
│   │   ├── ProductMockup.jsx
│   │   └── SettingsAccordion.jsx
│   ├── layout/                   # Layout subcomponents
│   │   ├── GradientBackground.jsx
│   │   └── SiteHeader.jsx
│   ├── sections/                 # Page sections
│   │   ├── HeroSection.jsx
│   │   ├── ConverterSection.jsx
│   │   ├── FeaturesSection.jsx
│   │   ├── ResultsSection.jsx
│   │   └── FooterSection.jsx
│   └── ui/                       # Reusable UI primitives
│       ├── Badge.jsx
│       ├── Button.jsx
│       ├── Card.jsx
│       ├── Select.jsx
│       └── Tabs.jsx
├── hooks/                        # Custom React hooks
│   ├── useConversion.js
│   └── useHistory.js
├── lib/                          # Utilities
│   ├── clientZip.js              # Client-side ZIP generation
│   └── utils.js
├── public/                       # Static assets
│   ├── file.svg
│   ├── globe.svg
│   ├── next.svg
│   ├── vercel.svg
│   └── window.svg
├── .gitignore
├── jsconfig.json
├── next.config.js
├── postcss.config.mjs
├── package.json
├── package-lock.json
├── AGENTS.md
├── CLAUDE.md
└── README.md
```

## Deployment on Vercel

1. Connect the repo on [Vercel](https://vercel.com).
2. Set **Root Directory** to `frontend`.
3. Add env var: `NEXT_PUBLIC_API_URL` → your Render backend URL.
4. Deploy — Vercel handles the rest.
