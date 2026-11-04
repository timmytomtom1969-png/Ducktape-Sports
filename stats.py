import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
CFBD_KEY = os.environ.get("CFBD_API_KEY", "")
APIS_KEY = os.environ.get("APISPORTS_KEY", "")
ESPN = "https://site.api.espn.com/apis/site/v2/sports"

# key matches the team keys in the app
TEAMS = {
    "pistons": {"sport": "basketball", "league": "nba", "id": "8"},
    "wings": {"sport": "hockey", "league": "nhl", "id": "5", "nhl": "DET"},
    "lions": {"sport": "football", "league": "nfl", "id": "8"},
    "michigan": {"sport": "football", "league": "college-football", "id": "130", "cfb": "Michigan"},
    "msu": {"sport": "football", "league": "college-football", "id": "127", "cfb": "Michigan State"},
    "tigers": {"sport": "baseball", "league": "mlb", "id": "6", "mlb": 116},
}


def get(url, headers=None):
    h = {"User-Agent": UA}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode("utf-8"))


def num(v):
    if isinstance(v, dict):
        v = v.get("displayValue", v.get("value", ""))
    return str(v)


def espn_team(t):
    base = "%s/%s/%s/teams/%s" % (ESPN, t["sport"], t["league"], t["id"])
    out = {"record": "", "standing": "", "stats": []}
    info = get(base).get("team", {})
    out["standing"] = info.get("standingSummary", "")
    logos = info.get("logos", [])
    dark = [l["href"] for l in logos if "dark" in (l.get("rel") or []) and "scoreboard" not in (l.get("rel") or [])]
    plain = [l["href"] for l in logos if l.get("href")]
    out["logo"] = (dark or plain or [info.get("logo", "")])[0].replace("http://", "https://")
    items = info.get("record", {}).get("items", [])
    if items:
        out["record"] = items[0].get("summary", "")
    return out, base


def espn_stats(base):
    cats = get(base + "/statistics").get("results", {}).get("stats", {}).get("categories", [])
    flat = []
    for c in cats:
        for s in c.get("stats", []):
            name = s.get("displayName") or s.get("name")
            val = s.get("displayValue")
            if name and val not in (None, ""):
                flat.append({"label": name, "value": str(val)})
    return flat[:80]


def broadcast_names(comp):
    names = []
    for key in ("broadcasts", "geoBroadcasts"):
        for b in comp.get(key, []) or []:
            m = (b.get("media") or {}).get("shortName", "")
            if m and m not in names:
                names.append(m)
            for n in b.get("names", []) or []:
                if n and n not in names:
                    names.append(n)
    return ", ".join(names[:3])


def espn_games(base):
    events = get(base + "/schedule").get("events", [])
    last, nxt = None, []
    for e in events:
        comp = e["competitions"][0]
        done = comp.get("status", {}).get("type", {}).get("completed", False)
        mine = opp = None
        for c in comp.get("competitors", []):
            if str(c.get("team", {}).get("id")) == base.rsplit("/", 1)[-1]:
                mine = c
            else:
                opp = c
        if not mine or not opp:
            continue
        g = {
            "date": e.get("date", ""),
            "opponent": opp["team"].get("shortDisplayName") or opp["team"].get("displayName", ""),
            "opponent_location": opp["team"].get("location", ""),
            "opponent_id": str(opp["team"].get("id", "")),
            "home": mine.get("homeAway") == "home",
            "my_score": num(mine.get("score", "")),
            "opp_score": num(opp.get("score", "")),
            "won": bool(mine.get("winner")),
            "channels": broadcast_names(comp),
        }
        if done:
            last = g
        else:
            nxt.append(g)
    return last, nxt[:3]


def nhl_leaders(code):
    d = get("https://api-web.nhle.com/v1/club-stats/%s/now" % code)
    out = []
    sk = sorted(d.get("skaters", []), key=lambda p: p.get("points", 0), reverse=True)[:4]
    for p in sk:
        name = p["firstName"]["default"] + " " + p["lastName"]["default"]
        out.append({"name": name, "line": "%d pts (%dG %dA)" % (p.get("points", 0), p.get("goals", 0), p.get("assists", 0))})
    gs = sorted(d.get("goalies", []), key=lambda p: p.get("gamesPlayed", 0), reverse=True)[:1]
    for p in gs:
        name = p["firstName"]["default"] + " " + p["lastName"]["default"]
        out.append({"name": name, "line": "%.3f save pct" % p.get("savePercentage", 0)})
    return out


def mlb_leaders(team_id):
    cats = "homeRuns,battingAverage,runsBattedIn,earnedRunAverage,strikeouts"
    d = get("https://statsapi.mlb.com/api/v1/teams/%d/leaders?leaderCategories=%s" % (team_id, cats))
    out = []
    for c in d.get("teamLeaders", []):
        if c.get("leaders"):
            top = c["leaders"][0]
            out.append({"name": top["person"]["fullName"], "line": "%s %s" % (top["value"], c["leaderCategory"])})
    return out[:5]


def cfb_stats(team, year):
    h = {"Authorization": "Bearer " + CFBD_KEY}
    q = urllib.parse.urlencode({"year": year, "team": team})
    d = get("https://api.collegefootballdata.com/stats/season?" + q, h)
    want = ["totalYards", "passingYards", "rushingYards", "points", "turnovers", "sacks"]
    got = {x["statName"]: x["statValue"] for x in d}
    return [{"label": w, "value": str(got[w])} for w in want if w in got]


def cfb_matchup(team, other):
    h = {"Authorization": "Bearer " + CFBD_KEY}
    q = urllib.parse.urlencode({"team1": team, "team2": other})
    d = get("https://api.collegefootballdata.com/teams/matchup?" + q, h)
    return {"team_wins": d.get("team1Wins"), "opp_wins": d.get("team2Wins"), "ties": d.get("ties")}


def espn_leaders(t):
    # Team leaders from ESPN's core data (works for the NBA and NFL where no other free source does).
    year = datetime.now(timezone.utc).year
    seasons = [year + 1, year] if t["league"] == "nba" else [year]
    lg = t["league"]
    last = None
    for season in seasons:
        url = "https://sports.core.api.espn.com/v2/sports/%s/leagues/%s/seasons/%d/types/2/teams/%s/leaders" % (
            t["sport"], lg, season, t["id"])
        try:
            d = get(url)
        except Exception as e:
            last = e
            continue
        out = []
        for cat in d.get("categories", [])[:5]:
            lead = (cat.get("leaders") or [None])[0]
            if not lead:
                continue
            ref = lead.get("athlete", {}).get("$ref", "").replace("http://", "https://")
            name = ""
            if ref:
                try:
                    name = get(ref).get("displayName", "")
                except Exception:
                    name = ""
            if name:
                out.append({"name": name, "line": "%s %s" % (lead.get("displayValue", ""), cat.get("displayName", cat.get("name", "")))})
        if out:
            return out
    if last:
        raise last
    return []


def build(key, t, report):
    out = {"record": "", "standing": "", "stats": [], "leaders": [], "last_game": None, "next_games": [], "matchup": {}}
    def step(name, fn):
        try:
            r = fn()
            report.append("%s: ok" % name)
            return r
        except Exception as e:
            report.append("%s: failed (%s)" % (name, str(e)[:70]))
            return None

    r = step("ESPN team", lambda: espn_team(t))
    base = None
    if r:
        info, base = r
        out.update(info)
    if base:
        s = step("ESPN stats", lambda: espn_stats(base))
        if s:
            out["stats"] = s
        g = step("ESPN games", lambda: espn_games(base))
        if g:
            out["last_game"], out["next_games"] = g
    if t["league"] in ("nba", "nfl"):
        l = step("ESPN leaders", lambda: espn_leaders(t))
        if l:
            out["leaders"] = l
    if t.get("nhl"):
        l = step("NHL leaders", lambda: nhl_leaders(t["nhl"]))
        if l:
            out["leaders"] = l
    if t.get("mlb"):
        l = step("MLB leaders", lambda: mlb_leaders(t["mlb"]))
        if l:
            out["leaders"] = l
    if t.get("cfb") and CFBD_KEY:
        year = datetime.now(timezone.utc).year
        s = step("CFBD stats", lambda: cfb_stats(t["cfb"], year))
        if s:
            out["stats"] = s
        if out["next_games"]:
            opp = out["next_games"][0]["opponent_location"]
            m = step("CFBD matchup", lambda: cfb_matchup(t["cfb"], opp))
            if m:
                out["matchup"] = m
    # Opponent snapshot for the matchup tile
    if out["next_games"] and out["next_games"][0].get("opponent_id"):
        oid = out["next_games"][0]["opponent_id"]
        ot = dict(t, id=oid)
        o = step("Opponent", lambda: espn_team(ot))
        if o:
            snap = {"record": o[0]["record"], "standing": o[0]["standing"]}
            st = step("Opponent stats", lambda: espn_stats(o[1]))
            if st:
                snap["stats"] = st
            out["matchup"]["opponent"] = snap
    return out


def apisports_probe():
    # Finds out what the free API-Sports plan allows for player stats.
    out = {}
    for name, host, search, path in (
        ("nba", "v2.nba.api-sports.io", "Detroit", "players/statistics"),
        ("nfl", "v1.american-football.api-sports.io", "Detroit", "players/statistics"),
    ):
        h = {"x-apisports-key": APIS_KEY}
        try:
            teams = get("https://%s/teams?search=%s" % (host, search), h)
            ids = [(x.get("id"), x.get("name")) for x in teams.get("response", [])][:4]
            note = {"teams": ids, "errors": teams.get("errors")}
            if ids:
                for season in (2026, 2025):
                    d = get("https://%s/%s?team=%s&season=%d" % (host, path, ids[0][0], season), h)
                    note["season%d" % season] = {"results": d.get("results"), "errors": d.get("errors")}
            out[name] = note
        except Exception as e:
            out[name] = {"failed": str(e)[:100]}
    return out


def main():
    result = {"updated": datetime.now(timezone.utc).isoformat(), "teams": {}, "report": {}}
    for key, t in TEAMS.items():
        report = []
        result["teams"][key] = build(key, t, report)
        result["report"][key] = ".  ".join(report)
        print(key, "->", result["report"][key])
    if APIS_KEY:
        result["apisports_probe"] = apisports_probe()
    with open("stats.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    main()
