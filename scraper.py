import html
import json
import urllib.request
import re
from datetime import datetime, timedelta, timezone
from time import mktime

import feedparser

# Look like a normal browser so fewer sites turn the request away.
feedparser.USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

MAX_AGE_DAYS = 30
MIN_TEXT = 200
MAX_ITEMS = 10

# Football rows skip stories that mention any of these.
BLOCKED = ["basketball", "hoops", "march madness", "izzo", "dusty may", "breslin", "crisler"]

# key matches the team keys in the app. Feeds with backup=True are used only
# if the regular feeds return nothing. must = only keep stories that mention it.
TEAMS = {
    "pistons": {
        "espn": ("basketball", "nba", "8"),
        "football": False,
        "feeds": [
            {"name": "Detroit Bad Boys", "urls": ["https://www.detroitbadboys.com/rss/current.xml"]},
        ],
    },
    "wings": {
        "espn": ("hockey", "nhl", "5"),
        "football": False,
        "feeds": [
            {"name": "Octopus Thrower", "fulltext": True, "urls": [
                "https://octopusthrower.com/feed/",
                "https://octopusthrower.com/rss/",
                "https://octopusthrower.com/?feed=rss2",
                "https://octopusthrower.com/feed/atom/",
                "https://www.octopusthrower.com/feed/",
                "https://octopusthrower.com/rss.xml",
            ]},
            {"name": "Winging It in Motown", "urls": ["https://www.wingingitinmotown.com/feed/"], "backup": True},
        ],
    },
    "lions": {
        "espn": ("football", "nfl", "8"),
        "football": False,
        "feeds": [
            {"name": "Pride of Detroit", "urls": ["https://www.prideofdetroit.com/rss/index.xml"]},
            {"name": "SideLion Report", "urls": ["https://sidelionreport.com/feed/"]},
            {"name": "Lions Lowdown", "urls": ["https://lionslowdown.com/feed/"]},
        ],
    },
    "michigan": {
        "espn": ("football", "college-football", "130"),
        "football": True,
        "feeds": [
            {"name": "Maize n Brew", "urls": ["https://www.maizenbrew.com/rss/index.xml"]},
            {"name": "Touch the Banner", "urls": ["https://touch-the-banner.com/feed/"]},
            {"name": "MGoBlog", "urls": ["https://mgoblog.com/category/topics/football/feed"]},
        ],
    },
    "msu": {
        "espn": ("football", "college-football", "127"),
        "football": True,
        "feeds": [
            {"name": "The Only Colors", "urls": ["https://www.theonlycolors.com/rss/index.xml"]},
        ],
    },
    "tigers": {
        "espn": ("baseball", "mlb", "6"),
        "football": False,
        "feeds": [
            {"name": "Bless You Boys", "urls": ["https://www.blessyouboys.com/rss/current.xml"]},
            {"name": "Motor City Bengals", "urls": ["https://motorcitybengals.com/feed/"]},
        ],
    },
}


def clean_html(text):
    # Keep paragraph breaks, drop tags and link debris.
    text = re.sub(r"(?i)<\s*br\s*/?>|</\s*(p|div|li|h[1-6]|blockquote)\s*>", "\n", text or "")
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text).replace(" ", " ").replace("￼", "")
    lines = [ln.strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if not (ln.startswith("The post ") and " appeared first on " in ln)]
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def entry_date(entry):
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            return datetime.fromtimestamp(mktime(t), tz=timezone.utc)
    return None


def entry_body(entry):
    content = entry.get("content")
    if content:
        return clean_html(content[0].get("value", ""))
    return clean_html(entry.get("summary", entry.get("description", "")))


def fetch_article(url):
    # Some feeds send only a short preview. Open the story page and keep its paragraphs.
    try:
        req = urllib.request.Request(url, headers={"User-Agent": feedparser.USER_AGENT})
        with urllib.request.urlopen(req, timeout=20) as r:
            page = r.read().decode("utf-8", errors="replace")
    except Exception:
        return ""
    m = re.search(r"(?is)<article\b.*?</article>", page)
    part = m.group(0) if m else page
    part = re.sub(r"(?is)<(script|style|nav|footer|aside|form|figure)\b.*?</\1>", "", part)
    paras = [clean_html(p) for p in re.findall(r"(?is)<p\b[^>]*>(.*?)</p>", part)]
    paras = [p for p in paras if len(p) > 40]
    return "\n\n".join(paras)


def fetch_feed(feed, notes):
    last = "no address"
    for url in feed["urls"]:
        try:
            parsed = feedparser.parse(url)
        except Exception as e:  # network or parse trouble
            last = str(e)
            continue
        status = parsed.get("status", 0)
        if parsed.entries:
            stories = []
            for e in parsed.entries:
                title = clean_html(e.get("title", "")).replace("\n", " ").strip()
                body = entry_body(e)
                if feed.get("fulltext") and len(body) < MIN_TEXT and e.get("link"):
                    body = fetch_article(e["link"]) or body
                if not title or len(body) < MIN_TEXT:
                    continue
                if feed.get("must") and feed["must"].lower() not in (title + " " + body).lower():
                    continue
                d = entry_date(e)
                stories.append({
                    "headline": title,
                    "body": body,
                    "source": feed["name"],
                    "date": d.isoformat() if d else "",
                })
            notes.append("%s: %d found" % (feed["name"], len(stories)))
            return stories
        last = "HTTP %s, no stories" % status if status else "unreachable"
    notes.append("%s: failed (%s)" % (feed["name"], last))
    return []


def espn_backup(team, notes):
    sport, league, tid = team["espn"]
    url = "https://site.api.espn.com/apis/site/v2/sports/%s/%s/news?team=%s&limit=25" % (sport, league, tid)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": feedparser.USER_AGENT})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception as e:
        notes.append("ESPN failed (%s)" % e)
        return []
    stories = []
    for a in data.get("articles", []):
        head = (a.get("headline") or "").strip()
        desc = (a.get("description") or "").strip()
        if not head or not desc or head.lower() == desc.lower() or a.get("type") == "Media":
            continue
        stories.append({"headline": head, "body": desc, "source": "ESPN", "date": a.get("published", "") or ""})
    notes.append("ESPN backup: %d found" % len(stories))
    return stories


def blocked(football, story):
    if not football:
        return False
    text = (story["headline"] + " " + story["body"][:400]).lower()
    return any(w in text for w in BLOCKED)


def team_news(team):
    notes = []
    stories = []
    for feed in team["feeds"]:
        if not feed.get("backup"):
            stories += fetch_feed(feed, notes)
    if not stories:
        for feed in team["feeds"]:
            if feed.get("backup"):
                stories += fetch_feed(feed, notes)

    if not stories:
        stories = espn_backup(team, notes)

    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)
    fresh, seen = [], set()
    for s in stories:
        try:
            if s["date"] and datetime.fromisoformat(s["date"].replace("Z", "+00:00")) < cutoff:
                continue
        except ValueError:
            pass
        if blocked(team["football"], s):
            continue
        key = s["headline"].lower()
        if key in seen:
            continue
        seen.add(key)
        fresh.append(s)
    fresh.sort(key=lambda s: s["date"] or "", reverse=True)
    notes.append("keeping %d" % len(fresh[:MAX_ITEMS]))
    return fresh[:MAX_ITEMS], notes


def main():
    out = {"updated": datetime.now(timezone.utc).isoformat(), "teams": {}, "report": {}}
    for key, team in TEAMS.items():
        stories, notes = team_news(team)
        out["teams"][key] = stories
        out["report"][key] = ".  ".join(notes)
        print(key, "->", out["report"][key])
    with open("news.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
