import json, logging, time
from datetime import datetime
from typing import Optional
import anthropic

logger = logging.getLogger(__name__)
MODEL = "claude-sonnet-4-20250514"
MAX_TOKENS = 900

SYSTEM_PROMPT = """You are a civic intelligence analyst specialising in Bengaluru, India.
Analyse news headlines about urban governance, environment, and law.
Always respond with ONLY a valid JSON object — no markdown, no explanation."""

PROMPT_TEMPLATE = """Analyse this Bengaluru civic news and return ONLY a JSON object:
{{
  "severity": "High" or "Medium" or "Low",
  "severity_note": "<one sentence on urgency>",
  "laws": ["<specific Indian act + section>"],
  "legal_points": ["<3-4 legal implications as full sentences>"],
  "civic_points": ["<3-4 civic implications as full sentences>"],
  "watch_points": ["<3 things to monitor next>"],
  "entities": ["<agencies, courts, locations, case numbers>"]
}}
Headline: {title}
Source: {source} | Category: {category} | Location: {location}
Excerpt: {excerpt}"""

def build_prompt(article):
    return PROMPT_TEMPLATE.format(
        title=article.get("title",""), source=article.get("source",""),
        category=article.get("category",""), location=article.get("location","Bengaluru"),
        excerpt=(article.get("excerpt","") or "")[:300])

def parse_analysis(raw):
    clean = raw.strip().lstrip("```json").lstrip("```").rstrip("```").strip()
    try:
        return json.loads(clean)
    except:
        return None

def write_analysis(session, article_id, parsed, raw, model):
    from db.models import Analysis
    row = session.query(Analysis).filter_by(article_id=article_id).first()
    if not row:
        row = Analysis(article_id=article_id)
        session.add(row)
    row.analysed_at = datetime.utcnow()
    row.model_used = model
    row.raw_response = raw
    if parsed:
        row.status = "done"
        row.severity = parsed.get("severity","Medium")
        row.severity_note = parsed.get("severity_note","")
        row.laws = parsed.get("laws",[])
        row.legal_points = parsed.get("legal_points",[])
        row.civic_points = parsed.get("civic_points",[])
        row.watch_points = parsed.get("watch_points",[])
        row.entities = parsed.get("entities",[])
    else:
        row.status = "failed"
    session.commit()

def analyse_single(article, client):
    try:
        msg = client.messages.create(model=MODEL, max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role":"user","content":build_prompt(article)}])
        return parse_analysis(msg.content[0].text)
    except Exception as e:
        logger.error("Analysis failed: %s", e)
        return None

def run_analysis_batch(session, anthropic_api_key):
    from db.models import Article, Analysis
    from datetime import date

    # Check daily limit
    today_start = datetime.combine(date.today(), datetime.min.time())
    done_today = session.query(Analysis).filter(
        Analysis.status == "done",
        Analysis.analysed_at >= today_start
    ).count()

    remaining = DAILY_ANALYSIS_LIMIT - done_today
    if remaining <= 0:
        logger.info("Daily analysis limit reached (%d/%d). Skipping.", done_today, DAILY_ANALYSIS_LIMIT)
        return

    logger.info("Daily limit: %d/%d used, will analyse up to %d articles.", done_today, DAILY_ANALYSIS_LIMIT, remaining)

    analysed_ids = {r.article_id for r in session.query(Analysis).filter_by(status="done").all()}
    pending = session.query(Article).filter(~Article.id.in_(analysed_ids)).order_by(Article.scraped_at.desc()).limit(remaining).all()
    if not pending:
        logger.info("No pending articles.")
        return
    client = anthropic.Anthropic(api_key=anthropic_api_key)
    for art in pending:
        data = {"id":art.id,"title":art.title,"source":art.source,"category":art.category,"location":art.location,"excerpt":art.excerpt}
        parsed = analyse_single(data, client)
        write_analysis(session, art.id, parsed, json.dumps(parsed or {}), MODEL)
        time.sleep(0.5)
    logger.info("Batch done: %d articles analysed today total.", done_today + len(pending))

DAILY_ANALYSIS_LIMIT = 10

def get_todays_analysis_count(session):
    from db.models import Analysis
    from datetime import date
    today_start = datetime.combine(date.today(), datetime.min.time())
    return session.query(Analysis).filter(
        Analysis.status == "done",
        Analysis.analysed_at >= today_start
    ).count()
