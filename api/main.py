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
ALLOWED_ORIGINS = ["http://localhost:3000", "http://localhost:5173"]
if _railway_url:
    ALLOWED_ORIGINS.extend([_railway_url, _railway_url.replace("https://", "http://")])


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
            "global_comparison": a.global_comparison or {},
            "timeline":      a.timeline or [],
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


# ── Keywords API ──────────────────────────────────────────────────────────────

@app.get("/api/keywords")
def list_keywords():
    session = get_session(engine)
    try:
        from db.models import Keyword, seed_keywords
        seed_keywords(session)
        rows = session.query(Keyword).order_by(Keyword.hit_count.desc()).all()
        return {"keywords": [
            {"id":r.id,"word":r.word,"category":r.category,
             "enabled":r.enabled,"is_default":r.is_default,
             "hit_count":r.hit_count or 0,
             "added_at":r.added_at.isoformat() if r.added_at else None}
            for r in rows
        ]}
    finally:
        session.close()

@app.post("/api/keywords")
def add_keyword(body: dict):
    word = (body.get("word","")).strip().lower()
    if not word:
        raise HTTPException(status_code=400, detail="word is required")
    session = get_session(engine)
    try:
        from db.models import Keyword
        existing = session.query(Keyword).filter_by(word=word).first()
        if existing:
            existing.enabled = True
            session.commit()
            return {"id":existing.id,"word":existing.word,"enabled":True,"message":"re-enabled"}
        row = Keyword(word=word, category=body.get("category",""),
                      enabled=True, is_default=False)
        session.add(row)
        session.commit()
        return {"id":row.id,"word":row.word,"category":row.category,"enabled":True}
    finally:
        session.close()

@app.patch("/api/keywords/{keyword_id}")
def toggle_keyword(keyword_id: int, body: dict):
    session = get_session(engine)
    try:
        from db.models import Keyword
        row = session.query(Keyword).filter_by(id=keyword_id).first()
        if not row: raise HTTPException(status_code=404, detail="Not found")
        row.enabled = body.get("enabled", not row.enabled)
        session.commit()
        return {"id":row.id,"word":row.word,"enabled":row.enabled}
    finally:
        session.close()

@app.delete("/api/keywords/{keyword_id}")
def delete_keyword(keyword_id: int):
    session = get_session(engine)
    try:
        from db.models import Keyword
        row = session.query(Keyword).filter_by(id=keyword_id).first()
        if not row: raise HTTPException(status_code=404, detail="Not found")
        if row.is_default:
            row.enabled = False
            session.commit()
            return {"message":"default keyword disabled"}
        session.delete(row)
        session.commit()
        return {"message":"deleted"}
    finally:
        session.close()




# ── Serve frontend HTML directly ──────────────────────────────────────────────
from fastapi.responses import FileResponse
import os as _os

_frontend = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "frontend")

@app.get("/")
def serve_index():
    return FileResponse(_os.path.join(_frontend, "index.html"))

@app.get("/keywords.html")
def serve_keywords():
    return FileResponse(_os.path.join(_frontend, "keywords.html"))
