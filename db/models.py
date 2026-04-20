from sqlalchemy import create_engine, Column, Integer, String, Text, Boolean, DateTime, JSON, ForeignKey
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

class Analysis(Base):
    __tablename__ = "analysis"
    id              = Column(Integer, primary_key=True)
    article_id      = Column(Integer, ForeignKey("articles.id"), unique=True)
    analysed_at     = Column(DateTime, default=datetime.utcnow)
    model_used      = Column(String(64))
    status          = Column(String(16), default="pending")
    severity        = Column(String(16))
    severity_note   = Column(Text)
    laws            = Column(JSON)
    legal_points    = Column(JSON)
    civic_points    = Column(JSON)
    watch_points    = Column(JSON)
    entities        = Column(JSON)
    raw_response      = Column(Text)
    global_comparison = Column(JSON)
    timeline          = Column(JSON)
    article           = relationship("Article", back_populates="analysis")

class Keyword(Base):
    __tablename__ = "keywords"
    id         = Column(Integer, primary_key=True)
    word       = Column(String(120), unique=True, nullable=False, index=True)
    category   = Column(String(32), default="")
    enabled    = Column(Boolean, default=True)
    is_default = Column(Boolean, default=False)
    hit_count  = Column(Integer, default=0)
    added_at   = Column(DateTime, default=datetime.utcnow)

class ScrapeLog(Base):
    __tablename__ = "scrape_log"
    id           = Column(Integer, primary_key=True)
    source_id    = Column(Integer, nullable=True)
    ran_at       = Column(DateTime, default=datetime.utcnow)
    new_articles = Column(Integer, default=0)
    errors       = Column(Text)

def get_engine(db_path="blr_news.db"):
    engine = create_engine(f"sqlite:///{db_path}", echo=False)
    Base.metadata.create_all(engine)
    return engine

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
    existing = session.query(Keyword).count()
    if existing > 0:
        return
    for word, cat in DEFAULT_KEYWORDS:
        session.add(Keyword(word=word, category=cat, enabled=True, is_default=True))
    session.commit()
