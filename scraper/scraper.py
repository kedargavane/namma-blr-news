import hashlib, logging, re
from datetime import datetime, timezone
from typing import Optional
import feedparser, requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)
HEADERS = {"User-Agent": "NammaBLRBot/1.0"}
TIMEOUT = 15

def url_hash(url):
    return hashlib.sha256(url.strip().encode()).hexdigest()

def clean(text):
    if not text: return ""
    text = text.encode("utf-8", "ignore").decode("utf-8")
    text = text.replace("\u00e2\u0080\u0099", "'").replace("\u00e2\u0080\u009c", '"').replace("\u00e2\u0080\u009d", '"').replace("\u00e2\u0080\u0094", "—")
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
            params={"q":source.get("query","Bengaluru"),"language":"en","sortBy":"publishedAt","pageSize":20,"apiKey":api_key},
            headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        for a in resp.json().get("articles",[]):
            url = clean(a.get("url",""))
            if not url: continue
            items.append({"title":clean(a.get("title","")),"url":url,"url_hash":url_hash(url),
                "source":a.get("source",{}).get("name",source["name"]),
                "published_at":datetime.utcnow(),"excerpt":clean(a.get("description",""))[:500],
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
            items.append({"title":clean(d.get("title","")),"url":link,"url_hash":url_hash(link),
                "source":f"r/{source['subreddit']}",
                "published_at":datetime.fromtimestamp(d.get("created_utc",0),tz=timezone.utc),
                "excerpt":clean(d.get("selftext",""))[:500],"raw_category":source.get("category","civic")})
    except Exception as e:
        logger.error("Reddit error: %s", e)
    return items

KEYWORDS = ["bengaluru","bangalore","bbmp","bwssb","bda","bmrcl","lake","encroachment",
    "sewage","tree","ngt","high court","karnataka","environment","forest","waste",
    "flood","urban","civic","infrastructure","pollution","green belt","wetland"]

BLOCKLIST = [
    "cricket","ipl","bjp","congress","election","poll","minister resigns",
    "actor","film","movie","court verdict unrelated","pm shri","school upgrade",
    "crypto","money laundering","abortion","rajya sabha","lok sabha",
    "flight diverted","turbulence","nanomaterial","research institute",
]

def is_relevant(article):
    text = (article["title"] + " " + article["excerpt"]).lower()
    if any(bl in text for bl in BLOCKLIST): return False
    return any(kw in text for kw in KEYWORDS)

def run_scraper(sources, config):
    all_items = []
    for src in sources:
        if not src.get("enabled", True): continue
        stype = src.get("type")
        if stype == "rss":     all_items.extend(fetch_rss(src))
        elif stype == "newsapi": all_items.extend(fetch_newsapi(src, config.get("newsapi_key","")))
        elif stype == "reddit":  all_items.extend(fetch_reddit(src))
    seen, filtered = set(), []
    for item in all_items:
        if item["url_hash"] in seen: continue
        seen.add(item["url_hash"])
        if is_relevant(item): filtered.append(item)
    logger.info("Scraper: %d raw → %d relevant", len(all_items), len(filtered))
    return filtered
