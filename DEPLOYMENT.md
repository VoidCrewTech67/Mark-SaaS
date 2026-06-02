# Deployment Guide

> Deploy the FastAPI backend to **Render** and the Next.js frontend to **Vercel** in ~15 minutes.

---

## Architecture Overview

```
┌─────────────────────────────────────┐
│         Browser (User)              │
└────────────────┬────────────────────┘
                 │ HTTPS
     ┌───────────▼────────────┐
     │  Next.js  (Vercel)     │  ← frontend/
     │  https://your-app      │
     └───────────┬────────────┘
                 │ REST API calls (HTTPS + CORS)
     ┌───────────▼────────────┐
     │  FastAPI  (Render)     │  ← backend/
     │  https://your-api      │
     └────────────────────────┘
```

---

## Prerequisites

- A [GitHub](https://github.com) account
- A [Render](https://render.com) account (free tier available)
- A [Vercel](https://vercel.com) account (free tier available)

---

## Step 1 — Push to GitHub

```bash
cd d:/Code/Mark          # your repo root (contains backend/ and frontend/)
git init
git add .
git commit -m "Initial commit — MarkItDown SaaS"
git remote add origin https://github.com/YOUR_USERNAME/markitdown.git
git push -u origin main
```

> ⚠️ Make sure `.gitignore` is committed first so no `.env` files or
> temp uploads are pushed.

---

## Step 2 — Deploy the Backend to Render

### 2a. Create a Blueprint

1. Go to [render.com/dashboard](https://dashboard.render.com/)
2. Click **New → Blueprint**
3. Connect your GitHub repo
4. Render will find `render.yaml` at the repo root and create the **markitdown-api** web service automatically

### 2b. Set the `ALLOWED_ORIGINS` environment variable

After the first deploy, you need to update CORS to allow your Vercel URL:

1. In the Render dashboard, open your **markitdown-api** service
2. Go to **Environment** tab
3. Edit `ALLOWED_ORIGINS`:

   ```
   http://localhost:3000,https://YOUR-APP.vercel.app
   ```

4. Click **Save Changes** → Render will redeploy automatically

### 2c. Wait for the Health Check

Once deployed, visit:
```
https://YOUR-RENDER-URL.onrender.com/api/health
```

Expected response:
```json
{
  "status": "ok",
  "ocr_available": true,
  "pdf_ocr_available": true,
  "token_backend": "tiktoken",
  "version": "1.0.0",
  "app_name": "MarkItDown Converter API"
}
```

> **Note on cold starts:** Render free tier spins down after inactivity.
> First request will take ~30s for EasyOCR model loading.
> Upgrade to **Starter** plan ($7/mo) to avoid spin-downs.

### 2d. Render Plan Recommendations

| Plan | RAM | Recommendation |
|---|---|---|
| Free | 512 MB | Development / light testing only |
| Starter | 512 MB | Small production (no spin-down) |
| Standard | 2 GB | ✅ Recommended for EasyOCR |
| Pro | 4 GB | High-volume / large documents |

---

## Step 3 — Deploy the Frontend to Vercel

### 3a. Import the project

1. Go to [vercel.com/new](https://vercel.com/new)
2. Click **Import Git Repository** → select your GitHub repo
3. Vercel detects Next.js automatically

### 3b. Configure the project

| Setting | Value |
|---|---|
| **Framework Preset** | Next.js (auto-detected) |
| **Root Directory** | `frontend` |
| **Build Command** | `npm run build` (default) |
| **Output Directory** | `.next` (default) |

### 3c. Add environment variable

In the **Environment Variables** section, add:

| Key | Value |
|---|---|
| `NEXT_PUBLIC_API_URL` | `https://YOUR-RENDER-URL.onrender.com` |

> Replace `YOUR-RENDER-URL` with the actual URL from Step 2.

### 3d. Deploy

Click **Deploy**. Vercel builds and deploys in ~2 minutes.

Your app will be live at: `https://your-project.vercel.app`

---

## Step 4 — Final Cross-Link

Now update Render with the Vercel URL:

1. Render dashboard → **markitdown-api** → **Environment**
2. Update `ALLOWED_ORIGINS`:
   ```
   https://your-project.vercel.app
   ```
   (remove localhost if this is a public production deployment)
3. Save → redeploy

---

## Local Development

To run both services locally with a single command:

```bash
cd d:/Code/Mark

# First-time setup
npm install                              # installs concurrently
pip install -r backend/requirements.txt  # Python deps

# Copy and configure env files
cp backend/.env.example backend/.env
cp frontend/.env.local.example frontend/.env.local
# Edit frontend/.env.local → NEXT_PUBLIC_API_URL=http://localhost:8000

# Run both servers
npm run dev
```

| Service | URL |
|---|---|
| Frontend | http://localhost:3000 |
| Backend API | http://localhost:8000 |
| API Docs (Swagger) | http://localhost:8000/docs |
| API Docs (ReDoc) | http://localhost:8000/redoc |

---

## Environment Variable Reference

### Backend (`backend/.env`)

| Variable | Default | Description |
|---|---|---|
| `ALLOWED_ORIGINS` | `http://localhost:3000` | Comma-separated CORS origins |
| `MAX_UPLOAD_SIZE_MB` | `150` | Per-file upload limit |
| `FILE_TTL_SECONDS` | `7200` | File retention time (2 hours) |
| `CLEANUP_INTERVAL_SECONDS` | `1800` | Cleanup job frequency (30 min) |
| `OCR_WARM_UP_ON_STARTUP` | `true` | Pre-load EasyOCR on startup |
| `UPLOAD_DIR` | `uploads` | Temp upload directory (relative) |
| `CONVERTED_DIR` | `converted` | Temp converted directory (relative) |
| `DEBUG` | `false` | Enable debug logging |
| `MARKITDOWN_TIMEOUT_S` | `120` | Per-conversion timeout (seconds) |
| `OCR_IMAGE_TIMEOUT_S` | `60` | Per-image OCR timeout (seconds) |

### Frontend (`frontend/.env.local`)

| Variable | Default | Description |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | `http://localhost:8000` | FastAPI backend base URL |

---

## Troubleshooting

### Backend won't start — `poppler not found`
The `buildCommand` in `render.yaml` installs `poppler-utils`. If running locally on Windows, download the [Poppler Windows binary](https://github.com/oschwartz10612/poppler-windows/releases) and add it to your `PATH`.

### EasyOCR model download fails on Render
EasyOCR downloads ~100 MB of model weights on first startup. This happens inside Render's ephemeral filesystem and is re-downloaded on every cold start. To avoid this, use the [Persistent Disk](https://render.com/docs/disks) feature and point `EASYOCR_MODULE_PATH` to a path on the disk.

### CORS errors in the browser
Make sure `ALLOWED_ORIGINS` on Render contains the **exact** Vercel URL — including `https://` and no trailing slash.

### Frontend shows "Failed to fetch"
Check that `NEXT_PUBLIC_API_URL` in Vercel matches your Render URL exactly. Remember: this variable must be set **before** the Vercel build runs (it gets baked into the JS bundle at build time).

---

## Security Checklist Before Going Public

- [ ] `DEBUG=false` in Render environment
- [ ] `ALLOWED_ORIGINS` contains only your Vercel URL (not `*` or localhost)
- [ ] No `.env` files committed to git (verify with `git ls-files | grep .env`)
- [ ] `backend/uploads/` and `backend/converted/` in `.gitignore`
- [ ] Render service is on a paid plan (free tier has no SLA)
