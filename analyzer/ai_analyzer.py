import json, logging, time, os
from datetime import datetime
from typing import Optional
import anthropic

logger = logging.getLogger(__name__)
MODEL = "claude-sonnet-4-5"
MAX_TOKENS = 1800
DAILY_ANALYSIS_LIMIT = 10

SYSTEM_PROMPT = """You are a civic intelligence analyst specialising in Bengaluru, India.
Analyse news headlines about urban governance, environment, and law.
Always respond with ONLY a valid JSON object — no markdown, no explanation."""

PROMPT_TEMPLATE = """Analyse this Bengaluru civic news and return ONLY a JSON object with exactly this structure:
{{
  "severity": "High" or "Medium" or "Low",
  "severity_note": "<one sentence on urgency>",
  "laws": ["<specific Indian act + section number>"],
  "legal_points": ["<3-4 specific legal implications as full sentences>"],
  "civic_points": ["<3-4 specific civic/urban implications as full sentences>"],
  "watch_points": ["<3 concrete things journalists or citizens should monitor>"],
  "entities": ["<agencies, courts, locations, case numbers, organisations>"],
  "global_comparison": {{
    "summary": "<2-3 sentences: how similar issues are handled in other cities or countries>",
    "examples": [
      {{"city": "<City, Country>", "approach": "<one sentence on what they did differently or better>"}},
      {{"city": "<City, Country>", "approach": "<one sentence on what they did differently or better>"}}
    ]
  }},
  "timeline": [
    {{"year": "<YYYY or YYYY Mon>", "event": "<one sentence describing what happened>"}},
    {{"year": "<YYYY or YYYY Mon>", "event": "<one sentence describing what happened>"}},
    {{"year": "<YYYY or YYYY Mon>", "event": "<one sentence — current event being reported>"}},
    {{"year": "<YYYY or YYYY Mon>", "event": "<one sentence — likely next development>"}}
  ]
}}

For timeline: include 3-5 entries showing the history of this specific issue leading up to today, plus one predicted next step. Order chronologically oldest to newest.
For global_comparison: pick 2 real cities that have faced similar urban/environmental challenges and describe their approach concisely.

Headline: {title}
Source: {source} | Category: {category} | Location: {location}
Excerpt: {excerpt}"""

def build_prompt(article):
    return PROMPT_TEMPLATE.format(
        title=article.get("title",""), source=article.get("source",""),
        category=article.get("category",""), location=article.get("location","Bengaluru"),
        excerpt=(article.get("excerpt","") or "")[:300])

def parse_analysis(raw):
    clean = raw.strip()
    if clean.startswith("```"):
        clean = "\n".join(clean.split("\n")[1:])
    if clean.endswith("```"):
        clean = clean.rsplit("```",1)[0]
    try:
        return json.loads(clean.strip())
    except Exception as e:
        logger.error("JSON parse error: %s | raw: %s", e, raw[:200])
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
        row.global_comparison = parsed.get("global_comparison",{})
        row.timeline = parsed.get("timeline",[])
    else:
        row.status = "failed"
    session.commit()

def analyse_single(article, client=None):
    # Always read key fresh from environment
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    logger.info("analyse_single: key length=%d, starts=%s", len(api_key), api_key[:10] if api_key else "EMPTY")
    if not api_key:
        logger.error("ANTHROPIC_API_KEY is empty!")
        return None
    try:
        c = anthropic.Anthropic(api_key=api_key)
        msg = c.messages.create(
            model=MODEL, max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role":"user","content":build_prompt(article)}])
        raw = msg.content[0].text
        logger.info("Claude raw response: %s", raw[:200])
        return parse_analysis(raw)
    except Exception as e:
        logger.error("Analysis failed: %s", e)
        return None

def run_analysis_batch(session, anthropic_api_key):
    from db.models import Article, Analysis
    from datetime import date

    today_start = datetime.combine(date.today(), datetime.min.time())
    done_today = session.query(Analysis).filter(
        Analysis.status == "done",
        Analysis.analysed_at >= today_start
    ).count()

    remaining = DAILY_ANALYSIS_LIMIT - done_today
    if remaining <= 0:
        logger.info("Daily limit reached (%d/%d).", done_today, DAILY_ANALYSIS_LIMIT)
        return

    logger.info("Daily limit: %d/%d used, will analyse up to %d.", done_today, DAILY_ANALYSIS_LIMIT, remaining)

    analysed_ids = {r.article_id for r in session.query(Analysis).filter_by(status="done").all()}
    pending = session.query(Article).filter(
        ~Article.id.in_(analysed_ids)
    ).order_by(Article.scraped_at.desc()).limit(remaining).all()

    if not pending:
        logger.info("No pending articles.")
        return

    for art in pending:
        data = {"id":art.id,"title":art.title,"source":art.source,
                "category":art.category,"location":art.location,"excerpt":art.excerpt}
        parsed = analyse_single(data)
        write_analysis(session, art.id, parsed, json.dumps(parsed or {}), MODEL)
        time.sleep(0.5)
    logger.info("Batch done: %d articles analysed today.", done_today + len(pending))
