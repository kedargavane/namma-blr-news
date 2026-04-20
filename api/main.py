"""
api/main.py — FastAPI backend, Railway-ready.

Adds:
  - GET /health   — Railway healthcheck probe
  - CORS locked to RAILWAY_STATIC_URL in production
  - Startup: runs one immediate scrape+analysis on first deploy
"""

import logging
import os
import json
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import desc

from db.models import Article, Analysis, get_engine, get_session
from analyzer.ai_analyzer import analyse_single, write_analysis
from scheduler.scheduler import start_scheduler, scrape_job, analysis_job
from config import CONFIG

import anthropic

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

engine = get_engine(CONFIG["db_path"])

_railway_url = os.getenv("RAILWAY_STATIC_URL", "")
cat > /tmp/fix_cors.py << 'EOF'
content = open("api/main.py").read()
old = '''_railway_url = os.getenv("RAILWAY_STATIC_URL", "")
ALLOWED_ORIGINS = ["http://localhost:3000", "http://localhost:5173"]
if _railway_url:
    ALLOWED_ORIGINS.extend([_railway_url, _railway_url.replace("https://", "http://")])'''
new = '''ALLOWED_ORIGINS = ["*"]'''
open("api/main.py", "w").write(content.replace(old, new))
print("done")
EOF
python3 /tmp/fix_cors.py


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=== App startup ===")
    if os.getenv("RUN_ON_STARTUP", "true").lower() == "true":
        try:
            scrape_job()
            analysis_job()
        except Exception as e:
            logger.warning("Startup job error (non-fatal): %s", e)
    scheduler = start_scheduler()
    yield
    scheduler.shutdown()


app = FastAPI(title="Namma BLR News API", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS,
                   allow_methods=["GET", "POST"], allow_headers=["*"])


@app.get("/health")
def health():
    return {"status": "ok", "db": CONFIG["db_path"]}


def serialize_article(art: Article) -> dict:
    a = art.analysis
    return {
        "id":           art.id,
        "title":        art.title,
        "url":          art.url,
        "source":       art.source,
        "published_at": art.published_at.isoformat() if art.published_at else None,
        "location":     art.location,
        "category":     art.category,
        "excerpt":      art.excerpt,
        "is_new":       art.is_new,
        "saved":        art.saved,
        "analysis": {
            "status":        a.status,
            "severity":      a.severity,
            "severity_note": a.severity_note,
            "laws":          a.laws or [],
            "legal_points":  a.legal_points or [],
            "civic_points":  a.civic_points or [],
            "watch_points":  a.watch_points or [],
            "entities":      a.entities or [],
            "analysed_at":   a.analysed_at.isoformat() if a.analysed_at else None,
        } if a else None,
    }


@app.get("/api/articles")
def list_articles(
    category: Optional[str] = Query(None),
    saved:    Optional[bool] = Query(None),
    q:        Optional[str]  = Query(None),
    page:     int            = Query(1, ge=1),
    per_page: int            = Query(10, ge=1, le=50),
):
    session = get_session(engine)
    try:
        query = session.query(Article).order_by(desc(Article.published_at))
        if category: query = query.filter(Article.category == category)
        if saved is not None: query = query.filter(Article.saved == saved)
        if q: query = query.filter(Article.title.ilike(f"%{q}%"))
        total    = query.count()
        articles = query.offset((page - 1) * per_page).limit(per_page).all()
        return {
            "total": total, "page": page, "per_page": per_page,
            "pages": max(1, (total + per_page - 1) // per_page),
            "articles": [serialize_article(a) for a in articles],
        }
    finally:
        session.close()


@app.get("/api/articles/{article_id}")
def get_article(article_id: int):
    session = get_session(engine)
    try:
        art = session.query(Article).filter_by(id=article_id).first()
        if not art: raise HTTPException(status_code=404, detail="Not found")
        return serialize_article(art)
    finally:
        session.close()


@app.post("/api/articles/{article_id}/analyze")
def trigger_analysis(article_id: int):
    session = get_session(engine)
    try:
        art = session.query(Article).filter_by(id=article_id).first()
        if not art: raise HTTPException(status_code=404, detail="Not found")
        client = anthropic.Anthropic(api_key=CONFIG["anthropic_api_key"])
        data   = {"id": art.id, "title": art.title, "source": art.source,
                  "category": art.category, "location": art.location, "excerpt": art.excerpt}
        parsed = analyse_single(data, client)
        write_analysis(session, art.id, parsed, json.dumps(parsed or {}), "claude-sonnet-4-20250514")
        return serialize_article(session.query(Article).filter_by(id=article_id).first())
    finally:
        session.close()


@app.post("/api/articles/{article_id}/save")
def toggle_save(article_id: int):
    session = get_session(engine)
    try:
        art = session.query(Article).filter_by(id=article_id).first()
        if not art: raise HTTPException(status_code=404, detail="Not found")
        art.saved = not art.saved
        session.commit()
        return {"id": art.id, "saved": art.saved}
    finally:
        session.close()


@app.get("/api/stats")
def get_stats():
    session = get_session(engine)
    try:
        return {
            "total_articles":   session.query(Article).count(),
            "analysed":         session.query(Analysis).filter_by(status="done").count(),
            "pending_analysis": session.query(Analysis).filter_by(status="pending").count(),
            "by_category":      {c: session.query(Article).filter_by(category=c).count()
                                 for c in ("env","legal","govt","infra","civic")},
            "by_severity":      {s: session.query(Analysis).filter_by(severity=s).count()
                                 for s in ("High","Medium","Low")},
        }
    finally:
        session.close()


@app.post("/api/admin/scrape")
def trigger_scrape():
    scrape_job(); return {"status": "scrape completed"}

@app.post("/api/admin/analyze")
def trigger_batch_analysis():
    analysis_job(); return {"status": "analysis batch submitted"}

from fastapi.staticfiles import StaticFiles
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
