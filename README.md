# Namma BLR Civic News Tracker — Railway Deploy Guide

## Architecture on Railway

```
Railway Service (single dyno)
├── FastAPI  (uvicorn, $PORT)       ← serves /api/* and /health
└── APScheduler (background threads)
    ├── scrape_job    every 2 hours
    └── analysis_job  every 2h 30m

Railway Volume → /data/blr_news.db  (SQLite, persists across deploys)
```

---

## Deploy in 5 steps

### Step 1 — Push to GitHub
```bash
git init && git add . && git commit -m "init"
git remote add origin https://github.com/YOU/namma-blr-news.git
git push -u origin main
```

### Step 2 — Create Railway project
1. Go to https://railway.app/new
2. Click **Deploy from GitHub repo** → select your repo
3. Railway detects Python automatically via nixpacks — click **Deploy**

### Step 3 — Add environment variables
Railway dashboard → your service → **Variables** tab:

| Variable | Value | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | `sk-ant-...` | Required |
| `NEWSAPI_KEY` | your key | Optional |
| `RAILWAY_VOLUME_MOUNT_PATH` | `/data` | Set after adding volume |
| `RUN_ON_STARTUP` | `true` | Runs scrape on first boot |
| `PYTHONUNBUFFERED` | `1` | Recommended for logs |

### Step 4 — Add a Volume (keeps DB across deploys)
Railway dashboard → service → **Volumes** tab:
- Click **Add Volume** → mount path: `/data` → size: 1 GB
- Railway will redeploy automatically

### Step 5 — Verify
```bash
railway logs --tail
# Look for: "Batch complete: XX analysed"

railway open
# Then visit /health and /api/articles
```

---

## Frontend connection

```javascript
const API = "https://yourapp.up.railway.app";

// Articles with pre-computed analysis already embedded
const { articles } = await fetch(`${API}/api/articles?page=1`).then(r => r.json());

// Each article.analysis contains:
// { severity, severity_note, laws[], legal_points[], civic_points[], watch_points[], entities[] }
```

## API endpoints

| Method | Path | Params |
|---|---|---|
| GET | `/health` | — |
| GET | `/api/articles` | category, q, page, per_page, saved |
| GET | `/api/articles/{id}` | — |
| POST | `/api/articles/{id}/analyze` | Re-run AI analysis |
| POST | `/api/articles/{id}/save` | Toggle bookmark |
| GET | `/api/stats` | — |
| POST | `/api/admin/scrape` | Manual trigger |
| POST | `/api/admin/analyze` | Manual trigger |

## Cost estimate

| Item | Cost/month |
|---|---|
| Railway Hobby plan | $5.00 |
| Railway Volume 1 GB | $0.25 |
| Anthropic Batch API (50 articles/day) | ~$0.45 |
| **Total** | **~$5.70/month** |

## Local dev

```bash
pip install -r requirements.txt
cp .env.example .env    # add ANTHROPIC_API_KEY
uvicorn api.main:app --reload --port 8000
# Swagger docs: http://localhost:8000/docs
```
