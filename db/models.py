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
    raw_response    = Column(Text)
    article         = relationship("Article", back_populates="analysis")

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
