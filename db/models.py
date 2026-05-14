"""
db/models.py — All SQLAlchemy models.
"""

from sqlalchemy import (
    create_engine, Column, Integer, String, Text,
    Boolean, DateTime, JSON, ForeignKey, text
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from datetime import datetime

Base = declarative_base()


class Article(Base):
    __tablename__ = "articles"
    id            = Column(Integer, primary_key=True)
    url_hash      = Column(String(64), unique=True, nullable=False, index=True)
    title         = Column(Text, nullable=False)
    url           = Column(Text, nullable=False)
    source        = Column(String(120))
    published_at  = Column(DateTime)
    scraped_at    = Column(DateTime, default=datetime.utcnow)
    location      = Column(String(120))
    category      = Column(String(32))
    excerpt       = Column(Text)
    is_new        = Column(Boolean, default=True)
    saved         = Column(Boolean, default=False)
    analysis      = relationship("Analysis", back_populates="article", uselist=False)
    bookmarks     = relationship("UserBookmark", back_populates="article")


class Analysis(Base):
    __tablename__ = "analysis"
    id                = Column(Integer, primary_key=True)
    article_id        = Column(Integer, ForeignKey("articles.id"), unique=True)
    analysed_at       = Column(DateTime, default=datetime.utcnow)
    model_used        = Column(String(64))
    status            = Column(String(16), default="pending")
    severity          = Column(String(16))
    severity_note     = Column(Text)
    laws              = Column(JSON)
    legal_points      = Column(JSON)
    civic_points      = Column(JSON)
    watch_points      = Column(JSON)
    entities          = Column(JSON)
    global_comparison = Column(JSON)
    timeline          = Column(JSON)
    key_personnel     = Column(JSON)
    raw_response      = Column(Text)
    analysed_by       = Column(Integer, ForeignKey("users.id"), nullable=True)
    article           = relationship("Article", back_populates="analysis")
    analyst           = relationship("User", back_populates="analyses")


class Keyword(Base):
    __tablename__ = "keywords"
    id         = Column(Integer, primary_key=True)
    word       = Column(String(120), unique=True, nullable=False, index=True)
    category   = Column(String(32), default="")
    enabled    = Column(Boolean, default=True)
    is_default = Column(Boolean, default=False)
    hit_count  = Column(Integer, default=0)
    added_at   = Column(DateTime, default=datetime.utcnow)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    creator    = relationship("User", back_populates="keywords")


class ScrapeLog(Base):
    __tablename__ = "scrape_log"
    id           = Column(Integer, primary_key=True)
    source_id    = Column(Integer, nullable=True)
    ran_at       = Column(DateTime, default=datetime.utcnow)
    new_articles = Column(Integer, default=0)
    errors       = Column(Text)


class User(Base):
    __tablename__ = "users"
    id            = Column(Integer, primary_key=True)
    email         = Column(String(200), unique=True, nullable=False, index=True)
    name          = Column(String(120), nullable=False)
    password_hash = Column(String(256), nullable=False)
    role          = Column(String(16), default="user")
    is_active     = Column(Boolean, default=True)
    created_at    = Column(DateTime, default=datetime.utcnow)
    last_login_at = Column(DateTime, nullable=True)
    bookmarks        = relationship("UserBookmark", back_populates="user")
    keywords         = relationship("Keyword", back_populates="creator")
    analyses         = relationship("Analysis", back_populates="analyst")
    feature_requests = relationship("FeatureRequest", back_populates="submitter")


class UserBookmark(Base):
    __tablename__ = "user_bookmarks"
    id            = Column(Integer, primary_key=True)
    user_id       = Column(Integer, ForeignKey("users.id"), nullable=False)
    article_id    = Column(Integer, ForeignKey("articles.id"), nullable=False)
    bookmarked_at = Column(DateTime, default=datetime.utcnow)
    user    = relationship("User", back_populates="bookmarks")
    article = relationship("Article", back_populates="bookmarks")


class AppSetting(Base):
    __tablename__ = "app_settings"
    key   = Column(String(64), primary_key=True)
    value = Column(Text, nullable=False)


class FeatureRequest(Base):
    __tablename__ = "feature_requests"
    id            = Column(Integer, primary_key=True)
    title         = Column(String(200), nullable=False)
    description   = Column(Text)
    status        = Column(String(20), default="submitted")
    # submitted | under_review | in_progress | completed | declined
    admin_comment = Column(Text)
    submitted_by  = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at    = Column(DateTime, default=datetime.utcnow)
    updated_at    = Column(DateTime, default=datetime.utcnow)
    submitter     = relationship("User", back_populates="feature_requests")


def get_engine(db_path="blr_news.db"):
    engine = create_engine(f"sqlite:///{db_path}", echo=False)
    Base.metadata.create_all(engine)
    _migrate(engine)
    return engine


def _migrate(engine):
    migrations = [
        ("analysis",         "global_comparison", "JSON"),
        ("analysis",         "timeline",          "JSON"),
        ("analysis",         "key_personnel",     "JSON"),
        ("analysis",         "analysed_by",       "INTEGER"),
        ("keywords",         "created_by",        "INTEGER"),
        ("feature_requests", "admin_comment",     "TEXT"),
        ("feature_requests", "updated_at",        "DATETIME"),
    ]
    with engine.connect() as conn:
        for table, col, col_type in migrations:
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}"))
                conn.commit()
            except Exception:
                pass


def get_session(engine):
    Session = sessionmaker(bind=engine)
    return Session()


DEFAULT_KEYWORDS = [
    ("bengaluru","env"),("bangalore","env"),("lake","env"),("wetland","env"),
    ("forest","env"),("tree","env"),("encroachment","env"),("sewage","env"),
    ("pollution","env"),("green belt","env"),("buffer zone","env"),("wildlife","env"),
    ("biodiversity","env"),("air quality","env"),("aqi","env"),("water body","env"),
    ("stormwater","env"),("turahalli","env"),("bellandur","env"),("varthur","env"),
    ("hebbal","env"),("high court","legal"),("supreme court","legal"),("ngt","legal"),
    ("national green tribunal","legal"),("pil","legal"),("stay order","legal"),
    ("fir","legal"),("court order","legal"),("karnataka hc","legal"),
    ("suo motu","legal"),("contempt","legal"),("bbmp","govt"),("bwssb","govt"),
    ("bda","govt"),("bmrcl","govt"),("karnataka govt","govt"),("master plan","govt"),
    ("notification","govt"),("circular","govt"),("directive","govt"),("swm","govt"),
    ("metro","infra"),("flyover","infra"),("road widening","infra"),
    ("white-topping","infra"),("infrastructure","infra"),("elevated","infra"),
    ("water supply","civic"),("garbage","civic"),("solid waste","civic"),
    ("pothole","civic"),("footpath","civic"),("ward","civic"),
    ("drainage","civic"),("flood","civic"),("urban","civic"),
]


def seed_keywords(session):
    if session.query(Keyword).count() > 0:
        return
    for word, cat in DEFAULT_KEYWORDS:
        session.add(Keyword(word=word, category=cat, enabled=True, is_default=True))
    session.commit()


def seed_admin(session):
    import os, bcrypt
    admin_email    = os.environ.get("ADMIN_EMAIL", "kedar.gavane@gmail.com")
    admin_password = os.environ.get("ADMIN_PASSWORD", "nammanews26")

    if not session.query(User).filter_by(email=admin_email).first():
        pw_hash = bcrypt.hashpw(admin_password.encode(), bcrypt.gensalt()).decode()
        session.add(User(
            email=admin_email, name="Admin",
            password_hash=pw_hash, role="admin", is_active=True
        ))
        session.commit()

    defaults = {
        "daily_quota": "10",
        "invite_code": os.environ.get("INVITE_CODE", "NammaBLR-2026"),
    }
    for key, val in defaults.items():
        if not session.query(AppSetting).filter_by(key=key).first():
            session.add(AppSetting(key=key, value=val))
    session.commit()


SEED_FEATURES = [
    {
        "title": "Individual login for each user",
        "description": "Each user should have their own account with login, bookmarks, and keyword tracking.",
        "status": "completed",
        "admin_comment": "Deployed. Users can register with an invite code, log in securely, and manage their own bookmarks and keywords independently. The admin dashboard tracks all user activity, analyses run, and keywords added.",
    },
    {
        "title": "Key personnel cited in articles",
        "description": "When an article mentions officials, judges, or activists by name, the analysis should extract and display their name, role, and organisation.",
        "status": "completed",
        "admin_comment": "Deployed. The AI analysis panel now includes a Key Personnel section that extracts named officials, judges, and activists from each article — showing their full name, role, and organisation as profile cards.",
    },
]


def seed_features(session):
    if session.query(FeatureRequest).count() > 0:
        return
    for f in SEED_FEATURES:
        session.add(FeatureRequest(
            title=f["title"],
            description=f["description"],
            status=f["status"],
            admin_comment=f["admin_comment"],
            submitted_by=None,
        ))
    session.commit()
