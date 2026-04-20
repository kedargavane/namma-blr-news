import hashlib, logging, re
from datetime import datetime, timezone
import feedparser, requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)
HEADERS = {"User-Agent": "NammaBLRBot/1.0"}
TIMEOUT = 15

FALLBACK_KEYWORDS = [
    "bengaluru","bangalore","bbmp","bwssb","bda","lake","encroachment",
    "sewage","pollution","ngt","high court","karnataka","environment",
    "forest","waste","flood","urban","civic","infrastructure","wetland",
]

def url_hash(url):
    return hashlib.sha256(url.strip().encode()).hexdigest()

def clean(text):
    if not text: return ""
    return re.sub(r"\s+", " ", text).strip()

def parse_date(entry):
    for f in ("published_parsed","updated_parsed"):
        t = getattr(entry, f, None)
        if t:
            try: return datetime(*t[:6], tzinfo=timezone.utc)
            except: pass
    return datetime.utcnow()

def fetch_rss(source):
    items = []
    try:
        feed = feedparser.parse(source["url"])
        for e in feed.entries:
            title = clean(e.get("title",""))
            link  = clean(e.get("link",""))
            if not title or not link: continue
            excerpt = clean(BeautifulSoup(e.get("summary",""), "html.parser").get_text())[:500]
            items.append({"title":title,"url":link,"url_hash":url_hash(link),
                "source":source["name"],"published_at":parse_date(e),
                "excerpt":excerpt,"raw_category":source.get("category","")})
    except Exception as e:
        logger.error("RSS error [%s]: %s", source["name"], e)
    return items

def fetch_newsapi(source, api_key):
    items = []
    if not api_key: return items
    try:
        resp = requests.get("https://newsapi.org/v2/everything",
            params={"q":source.get("query","Bengaluru"),"language":"en",
                    "sortBy":"publishedAt","pageSize":20,"apiKey":api_key},
            headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        for a in resp.json().get("articles",[]):
            url = clean(a.get("url",""))
            if not url: continue
            items.append({"title":clean(a.get("title","")),"url":url,
                "url_hash":url_hash(url),
                "source":a.get("source",{}).get("name",source["name"]),
                "published_at":datetime.utcnow(),
                "excerpt":clean(a.get("description",""))[:500],
                "raw_category":source.get("category","")})
    except Exception as e:
        logger.error("NewsAPI error: %s", e)
    return items

def fetch_reddit(source):
    items = []
    try:
        url = f"https://www.reddit.com/r/{source['subreddit']}/search.json?q={source.get('query','')}&sort=new&limit=25&restrict_sr=1"
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        for post in resp.json().get("data",{}).get("children",[]):
            d = post.get("data",{})
            link = f"https://reddit.com{d.get('permalink','')}"
            items.append({"title":clean(d.get("title","")),"url":link,
                "url_hash":url_hash(link),"source":f"r/{source['subreddit']}",
                "published_at":datetime.fromtimestamp(d.get("created_utc",0),tz=timezone.utc),
                "excerpt":clean(d.get("selftext",""))[:500],
                "raw_category":source.get("category","civic")})
    except Exception as e:
        logger.error("Reddit error: %s", e)
    return items

def get_active_keywords(session=None):
    """Load enabled keywords from DB, fall back to hardcoded list."""
    if session:
        try:
            from db.models import Keyword
            rows = session.query(Keyword).filter_by(enabled=True).all()
            if rows:
                return [r.word.lower() for r in rows]
        except Exception as e:
            logger.warning("Could not load keywords from DB: %s", e)
    return FALLBACK_KEYWORDS

BLOCKLIST = [
    "cricket","ipl","bjp","congress","election","poll","actor","film",
    "movie","pm shri","school upgrade","crypto","money laundering",
    "abortion","rajya sabha","lok sabha","flight diverted","turbulence",
    "nanomaterial","research institute","entertainment","celebrity",
]

def is_relevant(article, keywords):
    text = (article["title"] + " " + article["excerpt"]).lower()
    if any(bl in text for bl in BLOCKLIST): return False
    return any(kw in text for kw in keywords)

def increment_hit_counts(session, article, keywords):
    """Track which keywords matched this article."""
    if not session: return
    try:
        from db.models import Keyword
        text = (article["title"] + " " + article["excerpt"]).lower()
        for kw in keywords:
            if kw in text:
                row = session.query(Keyword).filter_by(word=kw).first()
                if row:
                    row.hit_count = (row.hit_count or 0) + 1
        session.commit()
    except Exception as e:
        logger.warning("hit count update failed: %s", e)

def run_scraper(sources, config, session=None):
    keywords = get_active_keywords(session)
    logger.info("Scraping with %d active keywords", len(keywords))
    all_items = []
    for src in sources:
        if not src.get("enabled", True): continue
        stype = src.get("type")
        if stype == "rss":      all_items.extend(fetch_rss(src))
        elif stype == "newsapi": all_items.extend(fetch_newsapi(src, config.get("newsapi_key","")))
        elif stype == "reddit":  all_items.extend(fetch_reddit(src))
    seen, filtered = set(), []
    for item in all_items:
        if item["url_hash"] in seen: continue
        seen.add(item["url_hash"])
        if is_relevant(item, keywords):
            if session: increment_hit_counts(session, item, keywords)
            filtered.append(item)
    logger.info("Scraper: %d raw → %d relevant", len(all_items), len(filtered))
    return filtered
