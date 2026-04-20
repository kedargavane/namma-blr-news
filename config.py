"""
config.py — All source definitions and runtime config.

On Railway: set ANTHROPIC_API_KEY and NEWSAPI_KEY in the Variables tab.
SQLite DB is stored on a Railway Volume mounted at /data.
Locally: copy .env.example → .env and fill in values.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# Railway volumes mount at /data; fall back to cwd locally
_DATA_DIR = os.getenv("RAILWAY_VOLUME_MOUNT_PATH", ".")

CONFIG = {
    "anthropic_api_key": os.getenv("ANTHROPIC_API_KEY", ""),
    "newsapi_key":       os.getenv("NEWSAPI_KEY", ""),
    "db_path":           os.path.join(_DATA_DIR, "blr_news.db"),
    "port":              int(os.getenv("PORT", 8000)),
}

# ── Source definitions ────────────────────────────────────────────────────────
# type: rss | newsapi | reddit | govt
# category: hint for classifier (env | legal | govt | infra | civic)

SOURCES = [

    # ── Google News RSS (no key) ──────────────────────────────────────────────
    {"type":"rss","name":"Google News — Lakes & Environment","enabled":True,"category":"env",
     "url":"https://news.google.com/rss/search?q=Bangalore+lake+environment&hl=en-IN&gl=IN&ceid=IN:en"},

    {"type":"rss","name":"Google News — BBMP & Civic","enabled":True,"category":"civic",
     "url":"https://news.google.com/rss/search?q=BBMP+Bengaluru&hl=en-IN&gl=IN&ceid=IN:en"},

    {"type":"rss","name":"Google News — Karnataka HC & NGT","enabled":True,"category":"legal",
     "url":"https://news.google.com/rss/search?q=Karnataka+High+Court+NGT+environment&hl=en-IN&gl=IN&ceid=IN:en"},

    {"type":"rss","name":"Google News — Urban Infrastructure","enabled":True,"category":"infra",
     "url":"https://news.google.com/rss/search?q=Bengaluru+metro+roads+infrastructure&hl=en-IN&gl=IN&ceid=IN:en"},

    {"type":"rss","name":"Google News — Tree Felling","enabled":True,"category":"env",
     "url":"https://news.google.com/rss/search?q=Bangalore+tree+felling+green+cover&hl=en-IN&gl=IN&ceid=IN:en"},

    {"type":"rss","name":"Google News — Water & BWSSB","enabled":True,"category":"civic",
     "url":"https://news.google.com/rss/search?q=BWSSB+Bengaluru+water&hl=en-IN&gl=IN&ceid=IN:en"},

    {"type":"rss","name":"Google News — Solid Waste","enabled":False,"category":"civic",
     "url":"https://news.google.com/rss/search?q=Bengaluru+solid+waste+garbage&hl=en-IN&gl=IN&ceid=IN:en"},

    # ── Direct RSS — major publications ──────────────────────────────────────
    {"type":"rss","name":"The Hindu — Bengaluru","enabled":True,"category":"",
     "url":"https://www.thehindu.com/news/cities/bangalore/feeder/default.rss"},

    {"type":"rss","name":"Deccan Herald — Bengaluru","enabled":True,"category":"",
     "url":"https://www.deccanherald.com/bangalore/feed"},

    {"type":"rss","name":"Times of India — Bengaluru","enabled":True,"category":"",
     "url":"https://timesofindia.indiatimes.com/rssfeeds/2147477281.cms"},

    {"type":"rss","name":"New Indian Express — Karnataka","enabled":True,"category":"",
     "url":"https://www.newindianexpress.com/states/karnataka/rssfeed/?id=227&getXmlFeed=true"},

    {"type":"rss","name":"Citizen Matters Bengaluru","enabled":True,"category":"civic",
     "url":"https://bengaluru.citizenmatters.in/feed"},

    {"type":"rss","name":"Scroll.in","enabled":False,"category":"",
     "url":"https://scroll.in/feed"},

    {"type":"rss","name":"The Wire","enabled":False,"category":"",
     "url":"https://thewire.in/feed"},

    # ── NewsAPI ───────────────────────────────────────────────────────────────
    {"type":"newsapi","name":"NewsAPI — Bengaluru environment","enabled":True,"category":"env",
     "query":"Bengaluru environment lake forest encroachment"},

    {"type":"newsapi","name":"NewsAPI — Bengaluru BBMP civic","enabled":True,"category":"civic",
     "query":"BBMP Bengaluru civic urban"},

    {"type":"newsapi","name":"NewsAPI — Karnataka NGT courts","enabled":True,"category":"legal",
     "query":"Karnataka NGT High Court Bengaluru"},

    # ── Reddit ────────────────────────────────────────────────────────────────
    {"type":"reddit","name":"r/bangalore — environment","enabled":True,"category":"civic",
     "subreddit":"bangalore","query":"environment lake BBMP water flood"},

    {"type":"reddit","name":"r/india — Bengaluru civic","enabled":False,"category":"civic",
     "subreddit":"india","query":"Bengaluru environment civic"},

    # ── Government portals (scraped) ──────────────────────────────────────────
    {"type":"govt","name":"BBMP Press Releases","enabled":True,"category":"govt",
     "url":"https://bbmp.gov.in/press-releases",
     "container_selector":"#press-release-list, .press-release, main",
     "base_url":"https://bbmp.gov.in"},

    {"type":"govt","name":"Karnataka Govt Circulars","enabled":True,"category":"govt",
     "url":"https://karnataka.gov.in/pages/circulars",
     "container_selector":"main, .content",
     "base_url":"https://karnataka.gov.in"},

    {"type":"govt","name":"BMRCL News","enabled":False,"category":"infra",
     "url":"https://bmrc.co.in/press-release",
     "container_selector":"main",
     "base_url":"https://bmrc.co.in"},
]
