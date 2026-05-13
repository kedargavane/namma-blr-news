"""
analyzer/ai_analyzer.py — Claude analysis pipeline.

Supports:
  - Single article on-demand analysis (used by API endpoint)
  - Batch analysis (used by scheduler, respects daily quota)

Analysis JSON schema includes:
  severity, severity_note, laws, legal_points, civic_points,
  watch_points, entities, global_comparison, timeline, key_personnel
"""

import json
import logging
import os
import time
from datetime import datetime
from typing import Optional

import anthropic

logger = logging.getLogger(__name__)

MODEL      = "claude-sonnet-4-5"
MAX_TOKENS = 1800

SYSTEM_PROMPT = """You are a civic intelligence analyst specialising in Bengaluru, India.
You analyse news headlines about urban governance, environment, and law.
Always respond with ONLY a valid JSON object — no markdown fences, no explanation, no preamble.
Be specific to Bengaluru's governance bodies: GBA, BBMP, BDA, BWSSB, BMRCL, Karnataka HC, NGT Southern Bench."""

PROMPT_TEMPLATE = """Analyse this Bengaluru civic news and return ONLY a JSON object with this exact structure:
{{
  "severity": "High" | "Medium" | "Low",
  "severity_note": "<one sentence explaining urgency>",
  "laws": ["<specific Indian act + section, e.g. Karnataka Forest Act 1963 §26>"],
  "legal_points": ["<3-4 specific legal implications as full sentences>"],
  "civic_points": ["<3-4 specific civic/urban implications as full sentences>"],
  "watch_points": ["<3 concrete things journalists or citizens should monitor next>"],
  "entities": ["<agencies, courts, locations, case numbers, organisations mentioned>"],
  "key_personnel": [
    {{"name": "<full name>", "role": "<official title or role>", "organisation": "<agency or body>"}}
  ],
  "global_comparison": {{
    "summary": "<2-3 sentences: how similar issues are handled in other cities or countries>",
    "examples": [
      {{"city": "<City, Country>", "approach": "<one sentence on what they did differently or better>"}},
      {{"city": "<City, Country>", "approach": "<one sentence on what they did differently or better>"}}
    ]
  }},
  "timeline": [
    {{"year": "<YYYY or Mon YYYY>", "event": "<one sentence describing what happened>"}},
    {{"year": "<YYYY or Mon YYYY>", "event": "<one sentence — current event being reported>"}},
    {{"year": "<YYYY or Mon YYYY>", "event": "<one sentence — likely next development>"}}
  ]
}}

Rules:
- key_personnel: list every named official, judge, activist or politician mentioned or implied. Include their exact title if stated. Empty array if none mentioned.
- timeline: 3-5 entries showing history of this specific issue chronologically, ending with a predicted next step marked with year "Next".
- global_comparison: pick 2 real cities that faced similar challenges. Be specific and factual.
- Return ONLY the JSON object. No text before or after.

Headline: {title}
Source: {source} | Category: {category} | Location: {location}
Excerpt: {excerpt}"""


def build_prompt(article: dict) -> str:
    return PROMPT_TEMPLATE.format(
        title    = article.get("title", ""),
        source   = article.get("source", ""),
        category = article.get("category", ""),
        location = article.get("location", "Bengaluru"),
        excerpt  = (article.get("excerpt", "") or "")[:400],
    )


def parse_analysis(raw: str) -> Optional[dict]:
    clean = raw.strip()
    if clean.startswith("```"):
        clean = "\n".join(clean.split("\n")[1:])
    if clean.endswith("```"):
        clean = clean.rsplit("```", 1)[0]
    try:
        return json.loads(clean.strip())
    except json.JSONDecodeError as e:
        logger.warning("JSON parse failed: %s | raw: %s", e, raw[:300])
        return None


def write_analysis(session, article_id: int, parsed: Optional[dict],
                   raw: str, model: str, user_id: Optional[int] = None):
    """Upsert analysis row. Stores all fields including new ones."""
    from db.models import Analysis

    row = session.query(Analysis).filter_by(article_id=article_id).first()
    if not row:
        row = Analysis(article_id=article_id)
        session.add(row)

    row.analysed_at  = datetime.utcnow()
    row.model_used   = model
    row.raw_response = raw
    row.analysed_by  = user_id

    if parsed:
        row.status            = "done"
        row.severity          = parsed.get("severity", "Medium")
        row.severity_note     = parsed.get("severity_note", "")
        row.laws              = parsed.get("laws", [])
        row.legal_points      = parsed.get("legal_points", [])
        row.civic_points      = parsed.get("civic_points", [])
        row.watch_points      = parsed.get("watch_points", [])
        row.entities          = parsed.get("entities", [])
        row.key_personnel     = parsed.get("key_personnel", [])
        row.global_comparison = parsed.get("global_comparison", {})
        row.timeline          = parsed.get("timeline", [])
    else:
        row.status = "failed"

    session.commit()


def get_daily_quota(session) -> int:
    """Read daily quota from app_settings, default 10."""
    try:
        from db.models import AppSetting
        setting = session.query(AppSetting).filter_by(key="daily_quota").first()
        return int(setting.value) if setting else 10
    except Exception:
        return 10


def get_todays_count(session) -> int:
    """How many analyses completed today."""
    from db.models import Analysis
    from datetime import date
    today_start = datetime.combine(date.today(), datetime.min.time())
    return session.query(Analysis).filter(
        Analysis.status == "done",
        Analysis.analysed_at >= today_start
    ).count()


def analyse_single(article: dict, client: anthropic.Anthropic = None,
                   user_id: Optional[int] = None) -> Optional[dict]:
    """
    Synchronous single-article analysis. Used by the API endpoint.
    Always reads API key fresh from environment.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        logger.error("ANTHROPIC_API_KEY not set")
        return None
    try:
        c = client or anthropic.Anthropic(api_key=api_key)
        msg = c.messages.create(
            model=MODEL, max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": build_prompt(article)}],
        )
        raw = msg.content[0].text
        logger.info("Claude response for article %s: %s...", article.get("id"), raw[:100])
        return parse_analysis(raw)
    except Exception as e:
        logger.error("analyse_single failed for article %s: %s", article.get("id"), e)
        return None


def run_analysis_batch(session, anthropic_api_key: str):
    """
    Called by scheduler. Respects daily quota from app_settings.
    Analyses up to (quota - done_today) pending articles.
    """
    from db.models import Article, Analysis

    quota     = get_daily_quota(session)
    done      = get_todays_count(session)
    remaining = quota - done

    if remaining <= 0:
        logger.info("Daily quota reached (%d/%d). Skipping batch.", done, quota)
        return

    logger.info("Quota: %d/%d used, will analyse up to %d articles.", done, quota, remaining)

    analysed_ids = {
        row.article_id
        for row in session.query(Analysis).filter(Analysis.status == "done").all()
    }
    pending = (
        session.query(Article)
        .filter(~Article.id.in_(analysed_ids))
        .order_by(Article.scraped_at.desc())
        .limit(remaining)
        .all()
    )

    if not pending:
        logger.info("No pending articles for analysis.")
        return

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        logger.error("ANTHROPIC_API_KEY not set — skipping batch")
        return

    client = anthropic.Anthropic(api_key=api_key)
    logger.info("Analysing %d articles individually (batch scheduler)", len(pending))

    for art in pending:
        data = {
            "id": art.id, "title": art.title, "source": art.source,
            "category": art.category, "location": art.location, "excerpt": art.excerpt,
        }
        parsed = analyse_single(data, client)
        write_analysis(session, art.id, parsed, json.dumps(parsed or {}), MODEL)
        time.sleep(0.5)  # rate limit courtesy

    logger.info("Batch done: %d articles processed.", len(pending))
