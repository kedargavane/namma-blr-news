import re
from typing import Optional

CATEGORY_RULES = [
    ("legal", ["high court","supreme court","ngt","national green tribunal","PIL","stay order","FIR","judgment","court order","karnataka hc","contempt","suo motu"]),
    ("govt",  ["bbmp circular","bbmp notification","government order","directive","notification","karnataka govt","master plan","policy","regulation","bylaw","commissioner","swm rule","bwssb circular"]),
    ("env",   ["lake","wetland","forest","tree","encroachment","sewage","pollution","environment","ecology","green belt","buffer zone","wildlife","biodiversity","air quality","AQI","water body"]),
    ("infra", ["metro","bmrcl","flyover","underpass","road widening","white-topping","infrastructure","construction","elevated","corridor","bda layout"]),
    ("civic", ["water supply","bwssb","garbage","solid waste","pothole","footpath","streetlight","power cut","ward","resident","citizen","complaint","drainage"]),
]

LOCATIONS = [
    "bellandur","varthur","hebbal","yelahanka","whitefield","koramangala",
    "indiranagar","jayanagar","jp nagar","rajajinagar","malleshwaram",
    "basavanagudi","electronic city","sarjapur","hsr layout","btm layout",
    "bannerghatta","outer ring road","kanakapura","turahalli","cubbon park",
    "lalbagh","ulsoor","kr puram","mahadevapura","bommanahalli",
]

def classify_category(title, excerpt=""):
    text = (title + " " + excerpt).lower()
    for cat, keywords in CATEGORY_RULES:
        if any(kw.lower() in text for kw in keywords):
            return cat
    return "civic"

def extract_location(title, excerpt=""):
    text = (title + " " + excerpt).lower()
    for loc in LOCATIONS:
        if loc in text:
            return loc.title()
    m = re.search(r"\bin ([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)", title)
    if m:
        return m.group(1)
    return "Bengaluru"

def classify(article):
    hint = article.get("raw_category", "")
    article["category"] = hint if hint in ("env","legal","govt","infra","civic") else classify_category(article.get("title",""), article.get("excerpt",""))
    article["location"] = extract_location(article.get("title",""), article.get("excerpt",""))
    return article
