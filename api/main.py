"""
api/main.py — Complete FastAPI backend with auth.

Endpoints:
  Public:
    GET  /health
    POST /api/auth/register
    POST /api/auth/login
    GET  /api/articles          (read-only, no auth needed)
    GET  /api/articles/{id}

  Authenticated (any logged-in user):
    GET  /api/me
    GET  /api/me/bookmarks
    POST /api/me/bookmarks/{article_id}   (toggle)
    GET  /api/me/keywords
    POST /api/articles/{id}/analyze
    GET  /api/analysis-quota
    POST /api/articles/submit
    GET  /api/keywords
    POST /api/keywords
    PATCH /api/keywords/{id}
    DELETE /api/keywords/{id}
    GET  /api/stats

  Admin only:
    GET  /api/admin/users
    GET  /api/admin/settings
    POST /api/admin/settings
    POST /api/admin/scrape
    POST /api/admin/analyze

  Static frontend:
    GET  /            → index.html
    GET  /keywords.html
    GET  /login.html
    GET  /register.html
    GET  /admin.html
"""

import logging
import os
import json
import bcrypt
import traceback
from contextlib import asynccontextmanager
from datetime import datetime, date
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import desc

from db.models import (
    Article, Analysis, Keyword, ScrapeLog, User, UserBookmark, AppSetting,
    get_engine, get_session, seed_keywords, seed_admin
)
from analyzer.ai_analyzer import (
    analyse_single, write_analysis, get_daily_quota, get_todays_count
)
from api.auth import create_token, get_current_user, get_optional_user, get_admin_user
from api.features_routes import router as features_router
from scheduler.scheduler import start_scheduler, scrape_job, analysis_job
from config import CONFIG

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

engine = get_engine(CONFIG["db_path"])

_FRONTEND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend")


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=== App startup ===")
    session = get_session(engine)
    try:
        seed_keywords(session)
        seed_admin(session)
        from db.models import seed_features
        seed_features(session)
    finally:
        session.close()

    if os.getenv("RUN_ON_STARTUP", "false").lower() == "true":
        try:
            scrape_job()
            analysis_job()
        except Exception as e:
            logger.warning("Startup job error (non-fatal): %s", e)

    scheduler = start_scheduler()
    yield
    scheduler.shutdown()
    logger.info("=== App shutdown ===")


app = FastAPI(title="Namma BLR News API", version="2.0.0", lifespan=lifespan)

app.include_router(features_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {
        "status": "ok",
        "db":     CONFIG["db_path"],
        "anthropic_key_set": bool(os.environ.get("ANTHROPIC_API_KEY", "").strip()),
    }


# ── Serialisers ───────────────────────────────────────────────────────────────

def serialize_analysis(a) -> Optional[dict]:
    if not a:
        return None
    return {
        "status":            a.status,
        "severity":          a.severity,
        "severity_note":     a.severity_note,
        "laws":              a.laws or [],
        "legal_points":      a.legal_points or [],
        "civic_points":      a.civic_points or [],
        "watch_points":      a.watch_points or [],
        "entities":          a.entities or [],
        "key_personnel":     a.key_personnel or [],
        "global_comparison": a.global_comparison or {},
        "timeline":          a.timeline or [],
        "analysed_at":       a.analysed_at.isoformat() if a.analysed_at else None,
    }


def serialize_article(art: Article, user_id: Optional[int] = None) -> dict:
    # check if this user bookmarked it
    is_bookmarked = False
    if user_id:
        is_bookmarked = any(b.user_id == user_id for b in art.bookmarks)
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
        "bookmarked":   is_bookmarked,
        "analysis":     serialize_analysis(art.analysis),
    }


def serialize_user(u: User) -> dict:
    return {
        "id":            u.id,
        "email":         u.email,
        "name":          u.name,
        "role":          u.role,
        "created_at":    u.created_at.isoformat() if u.created_at else None,
        "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
    }


# ── Auth routes ───────────────────────────────────────────────────────────────

@app.post("/api/auth/register")
def register(body: dict):
    email       = (body.get("email") or "").strip().lower()
    name        = (body.get("name") or "").strip()
    password    = (body.get("password") or "").strip()
    invite_code = (body.get("invite_code") or "").strip()

    if not email or not name or not password:
        raise HTTPException(status_code=400, detail="email, name and password are required")
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")

    session = get_session(engine)
    try:
        # validate invite code
        setting = session.query(AppSetting).filter_by(key="invite_code").first()
        valid_code = setting.value if setting else os.environ.get("INVITE_CODE", "NammaBLR-2026")
        if invite_code != valid_code:
            raise HTTPException(status_code=403, detail="Invalid invite code")

        if session.query(User).filter_by(email=email).first():
            raise HTTPException(status_code=409, detail="Email already registered")

        pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        user = User(email=email, name=name, password_hash=pw_hash, role="user")
        session.add(user)
        session.commit()
        session.refresh(user)

        token = create_token(user.id, user.role, user.name, user.email)
        return {"token": token, "user": serialize_user(user)}
    finally:
        session.close()


@app.post("/api/auth/login")
def login(body: dict):
    email    = (body.get("email") or "").strip().lower()
    password = (body.get("password") or "").strip()

    if not email or not password:
        raise HTTPException(status_code=400, detail="email and password are required")

    session = get_session(engine)
    try:
        user = session.query(User).filter_by(email=email, is_active=True).first()
        if not user or not bcrypt.checkpw(password.encode(), user.password_hash.encode()):
            raise HTTPException(status_code=401, detail="Invalid email or password")

        user.last_login_at = datetime.utcnow()
        session.commit()

        token = create_token(user.id, user.role, user.name, user.email)
        return {"token": token, "user": serialize_user(user)}
    finally:
        session.close()


# ── Me routes ─────────────────────────────────────────────────────────────────

@app.get("/api/me")
def get_me(current_user: dict = Depends(get_current_user)):
    session = get_session(engine)
    try:
        user = session.query(User).filter_by(id=int(current_user["sub"])).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # stats for this user
        bookmark_count = session.query(UserBookmark).filter_by(user_id=user.id).count()
        keyword_count  = session.query(Keyword).filter_by(created_by=user.id).count()
        analysis_count = session.query(Analysis).filter_by(analysed_by=user.id).count()
        today_start    = datetime.combine(date.today(), datetime.min.time())
        analyses_today = session.query(Analysis).filter(
            Analysis.analysed_by == user.id,
            Analysis.analysed_at >= today_start
        ).count()

        return {
            **serialize_user(user),
            "bookmark_count":  bookmark_count,
            "keyword_count":   keyword_count,
            "analysis_count":  analysis_count,
            "analyses_today":  analyses_today,
        }
    finally:
        session.close()


@app.get("/api/me/bookmarks")
def get_my_bookmarks(
    page: int = Query(1, ge=1),
    per_page: int = Query(10, ge=1, le=50),
    current_user: dict = Depends(get_current_user)
):
    session = get_session(engine)
    try:
        user_id = int(current_user["sub"])
        query   = session.query(UserBookmark).filter_by(user_id=user_id)\
                         .order_by(desc(UserBookmark.bookmarked_at))
        total   = query.count()
        bmarks  = query.offset((page-1)*per_page).limit(per_page).all()
        return {
            "total": total, "page": page, "per_page": per_page,
            "pages": max(1, (total + per_page - 1) // per_page),
            "articles": [serialize_article(b.article, user_id) for b in bmarks],
        }
    finally:
        session.close()


@app.post("/api/me/bookmarks/{article_id}")
def toggle_bookmark(
    article_id: int,
    current_user: dict = Depends(get_current_user)
):
    session = get_session(engine)
    try:
        user_id = int(current_user["sub"])
        art     = session.query(Article).filter_by(id=article_id).first()
        if not art:
            raise HTTPException(status_code=404, detail="Article not found")

        bmark = session.query(UserBookmark).filter_by(
            user_id=user_id, article_id=article_id).first()
        if bmark:
            session.delete(bmark)
            session.commit()
            return {"bookmarked": False}
        else:
            session.add(UserBookmark(user_id=user_id, article_id=article_id))
            session.commit()
            return {"bookmarked": True}
    finally:
        session.close()


@app.get("/api/me/keywords")
def get_my_keywords(current_user: dict = Depends(get_current_user)):
    session = get_session(engine)
    try:
        user_id = int(current_user["sub"])
        rows = session.query(Keyword).filter_by(created_by=user_id)\
                      .order_by(desc(Keyword.added_at)).all()
        return {"keywords": [
            {"id": r.id, "word": r.word, "category": r.category,
             "enabled": r.enabled, "hit_count": r.hit_count or 0,
             "added_at": r.added_at.isoformat() if r.added_at else None}
            for r in rows
        ]}
    finally:
        session.close()


# ── Article routes ────────────────────────────────────────────────────────────

@app.get("/api/articles")
def list_articles(
    category: Optional[str] = Query(None),
    q:        Optional[str]  = Query(None),
    page:     int            = Query(1, ge=1),
    per_page: int            = Query(10, ge=1, le=50),
    current_user: Optional[dict] = Depends(get_optional_user),
):
    session = get_session(engine)
    try:
        user_id = int(current_user["sub"]) if current_user else None
        query   = session.query(Article).order_by(desc(Article.published_at))
        if category:
            query = query.filter(Article.category == category)
        if q:
            query = query.filter(Article.title.ilike(f"%{q}%"))
        total    = query.count()
        articles = query.offset((page-1)*per_page).limit(per_page).all()
        return {
            "total": total, "page": page, "per_page": per_page,
            "pages": max(1, (total + per_page - 1) // per_page),
            "articles": [serialize_article(a, user_id) for a in articles],
        }
    finally:
        session.close()


@app.get("/api/articles/{article_id}")
def get_article(
    article_id: int,
    current_user: Optional[dict] = Depends(get_optional_user),
):
    session = get_session(engine)
    try:
        user_id = int(current_user["sub"]) if current_user else None
        art = session.query(Article).filter_by(id=article_id).first()
        if not art:
            raise HTTPException(status_code=404, detail="Not found")
        return serialize_article(art, user_id)
    finally:
        session.close()


@app.post("/api/articles/{article_id}/analyze")
def trigger_analysis(
    article_id: int,
    current_user: dict = Depends(get_current_user),
):
    session = get_session(engine)
    try:
        user_id = int(current_user["sub"])
        art = session.query(Article).filter_by(id=article_id).first()
        if not art:
            raise HTTPException(status_code=404, detail="Article not found")

        # check quota
        quota     = get_daily_quota(session)
        done      = get_todays_count(session)
        if done >= quota:
            raise HTTPException(
                status_code=429,
                detail=f"Daily analysis quota of {quota} reached. Resets at midnight."
            )

        api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not api_key:
            raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not configured")

        logger.info("Analyzing article %d for user %d", article_id, user_id)
        data   = {"id": art.id, "title": art.title, "source": art.source,
                  "category": art.category, "location": art.location, "excerpt": art.excerpt}
        parsed = analyse_single(data)
        write_analysis(session, art.id, parsed, json.dumps(parsed or {}), "claude-sonnet-4-5", user_id)

        user_id_opt = int(current_user["sub"]) if current_user else None
        return serialize_article(
            session.query(Article).filter_by(id=article_id).first(), user_id_opt)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Analysis error: %s\n%s", e, traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        session.close()


@app.post("/api/articles/submit")
def submit_article(
    body: dict,
    current_user: dict = Depends(get_current_user),
):
    import hashlib
    import requests as req
    from bs4 import BeautifulSoup
    from urllib.parse import urlparse
    from analyzer.classifier import classify

    url = (body.get("url") or "").strip()
    if not url or not url.startswith("http"):
        raise HTTPException(status_code=400, detail="Valid URL required")

    uh = hashlib.sha256(url.encode()).hexdigest()
    session = get_session(engine)
    try:
        user_id = int(current_user["sub"])
        existing = session.query(Article).filter_by(url_hash=uh).first()
        if existing:
            return {**serialize_article(existing, user_id), "message": "already_exists"}

        try:
            headers = {"User-Agent": "Mozilla/5.0 (compatible; NammaBLRBot/1.0)"}
            resp = req.get(url, headers=headers, timeout=15, allow_redirects=True)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Could not fetch URL: {e}")

        def og(name):
            tag = soup.find("meta", property=f"og:{name}")
            return (tag.get("content") or "").strip() if tag else ""

        def meta(name):
            tag = soup.find("meta", attrs={"name": name})
            return (tag.get("content") or "").strip() if tag else ""

        title   = og("title") or (soup.title.string.strip() if soup.title else "") or url
        excerpt = og("description") or meta("description") or ""
        domain  = urlparse(url).netloc.replace("www.", "")

        source_map = {
            "thehindu.com": "The Hindu", "deccanherald.com": "Deccan Herald",
            "timesofindia.com": "Times of India", "thenewsminute.com": "The News Minute",
            "newindianexpress.com": "New Indian Express",
            "bengaluru.citizenmatters.in": "Citizen Matters",
            "scroll.in": "Scroll", "thewire.in": "The Wire",
            "ndtv.com": "NDTV", "theprint.in": "The Print",
            "livelaw.in": "LiveLaw", "downtoearth.org.in": "Down To Earth",
            "sandrp.in": "SANDRP",
        }
        source = source_map.get(domain, domain) + " ★"

        pub_date = None
        for attr in [("property","article:published_time"),("name","publishdate")]:
            tag = soup.find("meta", {attr[0]: attr[1]})
            if tag and tag.get("content"):
                try:
                    pub_date = datetime.fromisoformat(tag["content"][:19])
                    break
                except Exception:
                    pass
        if not pub_date:
            pub_date = datetime.utcnow()

        art_data = classify({
            "title": title[:500], "url": url, "url_hash": uh,
            "source": source, "published_at": pub_date,
            "excerpt": excerpt[:500], "raw_category": "",
        })

        row = Article(
            url_hash=uh, title=art_data["title"], url=url, source=source,
            published_at=pub_date, location=art_data["location"],
            category=art_data["category"], excerpt=excerpt[:500],
            is_new=True, saved=False,
        )
        session.add(row)
        session.commit()
        session.refresh(row)
        return {**serialize_article(row, user_id), "message": "added"}
    finally:
        session.close()


# ── Analysis quota ────────────────────────────────────────────────────────────

@app.get("/api/analysis-quota")
def get_quota(current_user: dict = Depends(get_current_user)):
    session = get_session(engine)
    try:
        quota = get_daily_quota(session)
        done  = get_todays_count(session)
        return {
            "limit":      quota,
            "used_today": done,
            "remaining":  max(0, quota - done),
        }
    finally:
        session.close()


# ── Stats ─────────────────────────────────────────────────────────────────────

@app.get("/api/stats")
def get_stats(current_user: Optional[dict] = Depends(get_optional_user)):
    session = get_session(engine)
    try:
        quota = get_daily_quota(session)
        done  = get_todays_count(session)
        return {
            "total_articles":   session.query(Article).count(),
            "analysed":         session.query(Analysis).filter_by(status="done").count(),
            "pending_analysis": session.query(Analysis).filter_by(status="pending").count(),
            "by_category":      {c: session.query(Article).filter_by(category=c).count()
                                 for c in ("env","legal","govt","infra","civic")},
            "by_severity":      {s: session.query(Analysis).filter_by(severity=s).count()
                                 for s in ("High","Medium","Low")},
            "quota_limit":      quota,
            "quota_used":       done,
            "quota_remaining":  max(0, quota - done),
        }
    finally:
        session.close()


# ── Keywords ──────────────────────────────────────────────────────────────────

@app.get("/api/keywords")
def list_keywords(current_user: dict = Depends(get_current_user)):
    session = get_session(engine)
    try:
        rows = session.query(Keyword).order_by(desc(Keyword.hit_count)).all()
        return {"keywords": [
            {"id": r.id, "word": r.word, "category": r.category,
             "enabled": r.enabled, "is_default": r.is_default,
             "hit_count": r.hit_count or 0,
             "created_by": r.created_by,
             "added_at": r.added_at.isoformat() if r.added_at else None}
            for r in rows
        ]}
    finally:
        session.close()


@app.post("/api/keywords")
def add_keyword(body: dict, current_user: dict = Depends(get_current_user)):
    word = (body.get("word") or "").strip().lower()
    if not word:
        raise HTTPException(status_code=400, detail="word is required")
    session = get_session(engine)
    try:
        user_id  = int(current_user["sub"])
        existing = session.query(Keyword).filter_by(word=word).first()
        if existing:
            existing.enabled = True
            session.commit()
            return {"id": existing.id, "word": existing.word, "enabled": True, "message": "re-enabled"}
        row = Keyword(word=word, category=body.get("category", ""),
                      enabled=True, is_default=False, created_by=user_id)
        session.add(row)
        session.commit()
        return {"id": row.id, "word": row.word, "category": row.category, "enabled": True}
    finally:
        session.close()


@app.patch("/api/keywords/{keyword_id}")
def toggle_keyword(keyword_id: int, body: dict,
                   current_user: dict = Depends(get_current_user)):
    session = get_session(engine)
    try:
        row = session.query(Keyword).filter_by(id=keyword_id).first()
        if not row:
            raise HTTPException(status_code=404, detail="Not found")
        row.enabled = body.get("enabled", not row.enabled)
        session.commit()
        return {"id": row.id, "word": row.word, "enabled": row.enabled}
    finally:
        session.close()


@app.delete("/api/keywords/{keyword_id}")
def delete_keyword(keyword_id: int, current_user: dict = Depends(get_current_user)):
    session = get_session(engine)
    try:
        row = session.query(Keyword).filter_by(id=keyword_id).first()
        if not row:
            raise HTTPException(status_code=404, detail="Not found")
        if row.is_default:
            row.enabled = False
            session.commit()
            return {"message": "default keyword disabled"}
        session.delete(row)
        session.commit()
        return {"message": "deleted"}
    finally:
        session.close()


# ── Admin routes ──────────────────────────────────────────────────────────────

@app.get("/api/admin/users")
def admin_list_users(admin: dict = Depends(get_admin_user)):
    session = get_session(engine)
    try:
        today_start = datetime.combine(date.today(), datetime.min.time())
        users = session.query(User).order_by(desc(User.created_at)).all()
        result = []
        for u in users:
            bcount = session.query(UserBookmark).filter_by(user_id=u.id).count()
            kcount = session.query(Keyword).filter_by(created_by=u.id).count()
            acount = session.query(Analysis).filter_by(analysed_by=u.id).count()
            atoday = session.query(Analysis).filter(
                Analysis.analysed_by == u.id,
                Analysis.analysed_at >= today_start
            ).count()
            result.append({
                **serialize_user(u),
                "bookmark_count":  bcount,
                "keyword_count":   kcount,
                "analysis_count":  acount,
                "analyses_today":  atoday,
            })
        return {"users": result}
    finally:
        session.close()


@app.get("/api/admin/settings")
def admin_get_settings(admin: dict = Depends(get_admin_user)):
    session = get_session(engine)
    try:
        rows = session.query(AppSetting).all()
        return {"settings": {r.key: r.value for r in rows}}
    finally:
        session.close()


@app.post("/api/admin/settings")
def admin_update_settings(body: dict, admin: dict = Depends(get_admin_user)):
    session = get_session(engine)
    try:
        for key, val in body.items():
            row = session.query(AppSetting).filter_by(key=key).first()
            if row:
                row.value = str(val)
            else:
                session.add(AppSetting(key=key, value=str(val)))
        session.commit()
        rows = session.query(AppSetting).all()
        return {"settings": {r.key: r.value for r in rows}}
    finally:
        session.close()


@app.post("/api/admin/scrape")
def trigger_scrape(admin: dict = Depends(get_admin_user)):
    scrape_job()
    return {"status": "scrape completed"}


@app.post("/api/admin/analyze")
def trigger_batch_analysis(admin: dict = Depends(get_admin_user)):
    analysis_job()
    return {"status": "analysis batch submitted"}


# ── Serve frontend ────────────────────────────────────────────────────────────

def _fe(filename: str):
    path = os.path.join(_FRONTEND, filename)
    if os.path.exists(path):
        return FileResponse(path)
    raise HTTPException(status_code=404, detail=f"{filename} not found")


@app.get("/")
def serve_index():
    return _fe("index.html")

@app.get("/login.html")
def serve_login():
    return _fe("login.html")

@app.get("/register.html")
def serve_register():
    return _fe("register.html")

@app.get("/keywords.html")
def serve_keywords():
    return _fe("keywords.html")

@app.get("/admin.html")
def serve_admin():
    return _fe("admin.html")

@app.get("/features.html")
def serve_features():
    return _fe("features.html")
