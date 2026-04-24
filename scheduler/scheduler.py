import logging
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from db.models import Article, Analysis, ScrapeLog, get_engine, get_session, seed_keywords
from scraper.scraper import run_scraper
from analyzer.classifier import classify
from analyzer.ai_analyzer import run_analysis_batch
from config import CONFIG, SOURCES

logger = logging.getLogger(__name__)
engine = get_engine(CONFIG["db_path"])

def scrape_job():
    logger.info("=== SCRAPE JOB START ===")
    session = get_session(engine)
    try:
        seed_keywords(session)
        articles = run_scraper(SOURCES, CONFIG, session)
        new_count = 0
        for art in articles:
            if session.query(Article).filter_by(url_hash=art["url_hash"]).first(): continue
            art = classify(art)
            session.add(Article(
                url_hash=art["url_hash"], title=art["title"], url=art["url"],
                source=art["source"], published_at=art["published_at"],
                location=art["location"], category=art["category"],
                excerpt=art["excerpt"], is_new=True))
            new_count += 1
        session.commit()
        session.add(ScrapeLog(new_articles=new_count))
        session.commit()
        logger.info("Scrape done: %d new articles", new_count)
    except Exception as e:
        logger.error("Scrape error: %s", e)
        session.rollback()
    finally:
        session.close()

def analysis_job():
    logger.info("=== ANALYSIS JOB START ===")
    session = get_session(engine)
    try:
        run_analysis_batch(session, CONFIG["anthropic_api_key"])
    except Exception as e:
        logger.error("Analysis error: %s", e)
    finally:
        session.close()

def cleanup_job():
    from datetime import timedelta
    session = get_session(engine)
    try:
        cutoff = datetime.utcnow() - timedelta(days=30)
        old = session.query(Article).filter(
            Article.scraped_at < cutoff, Article.is_new == True).all()
        for a in old: a.is_new = False
        session.commit()
    finally:
        session.close()

def start_scheduler():
    scheduler = BackgroundScheduler(timezone="Asia/Kolkata")
    scheduler.add_job(scrape_job, IntervalTrigger(hours=2), id="scrape", replace_existing=True)
    # analysis_job disabled — triggered manually via API only
    # scheduler.add_job(analysis_job, IntervalTrigger(hours=2, start_date="2024-01-01 00:30:00"), id="analysis", replace_existing=True)
    scheduler.add_job(cleanup_job, CronTrigger(hour=3, minute=0, timezone="Asia/Kolkata"), id="cleanup", replace_existing=True)
    scheduler.start()
    logger.info("Scheduler started.")
    return scheduler
