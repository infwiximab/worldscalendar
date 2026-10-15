#!/usr/bin/env python3
"""
Worlds Calendar — builds an auto-updating iCalendar (.ics) feed of
League of Legends esports matches from the official lolesports schedule API.

Subscribe to the generated file in Apple Calendar (webcal://) and new
matches, start-time changes and knockout teams appear automatically.

No dependencies beyond the Python 3.9+ standard library.

Settings (all optional, via environment variables):
  LEAGUES        comma-separated league slugs        default: worlds
                 e.g. "worlds,msi,lec,lck"
  TEAMS          only include matches with these teams (code or name)
                 e.g. "T1,G2,FNC"  — blank = every match
  ALARM_MINUTES  add a reminder this many minutes before each match, e.g. 15
  SHOW_RESULTS   "1" to put scores in finished matches (spoilers!)   default: off
  CAL_NAME       calendar name shown in Apple Calendar
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.parse
import urllib.request

API_BASE = "https://esports-api.lolesports.com/persisted/gw"
# The public key lolesports.com itself uses (widely documented); override with LOLESPORTS_API_KEY.
DEFAULT_API_KEY = "0TvQnueqKa5mxJntVWt0w4LpLfEkrV1Ta8rQBb9Z"
USER_AGENT = "worlds-calendar/1.0 (+personal calendar feed)"
LOOKBACK_DAYS = 60   # keep recent results, drop last year's tournament
MAX_PAGES = 25       # safety cap when paging through the schedule


# ----------------------------------------------------------------- API ----

def api_get(endpoint: str, **params) -> dict:
    params = {k: v for k, v in params.items() if v is not None}
    params.setdefault("hl", "en-GB")
    url = f"{API_BASE}/{endpoint}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={
        "x-api-key": os.environ.get("LOLESPORTS_API_KEY") or DEFAULT_API_KEY,
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    })
    last_err: Exception | None = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except Exception as err:  # network blip, 5xx, rate limit…
            last_err = err
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"lolesports API call {endpoint} failed: {last_err}")


def get_leagues() -> dict[str, dict]:
    data = api_get("getLeagues")
    return {lg["slug"]: lg for lg in data["data"]["leagues"]}


def get_schedule_events(league_id: str, since: dt.datetime) -> list[dict]:
    """Walk the paged schedule forwards (all future) and backwards (back to `since`)."""
    first = api_get("getSchedule", leagueId=league_id)["data"]["schedule"]
    events = list(first.get("events", []))

    token, pages = (first.get("pages") or {}).get("newer"), 0
    while token and pages < MAX_PAGES:
        sched = api_get("getSchedule", leagueId=league_id, pageToken=token)["data"]["schedule"]
        events += sched.get("events", [])
        token, pages = (sched.get("pages") or {}).get("newer"), pages + 1

    token, pages = (first.get("pages") or {}).get("older"), 0
    while token and pages < MAX_PAGES:
        oldest = min((parse_time(e["startTime"]) for e in events), default=None)
        if oldest and oldest < since:
            break
        sched = api_get("getSchedule", leagueId=league_id, pageToken=token)["data"]["schedule"]
        events += sched.get("events", [])
        token, pages = (sched.get("pages") or {}).get("older"), pages + 1

    return events


# ------------------------------------------------------------- helpers ----

def parse_time(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(dt.timezone.utc)


def ics_time(t: dt.datetime) -> str:
    return t.astimezone(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def ics_escape(text: str) -> str:
    return (text.replace("\\", "\\\\").replace(";", "\\;")
                .replace(",", "\\,").replace("\r\n", "\\n").replace("\n", "\\n"))


def fold(line: str) -> str:
    """RFC 5545: lines over 75 octets are folded with CRLF + space."""
    out, cur = [], b""
    for ch in line:
        b = ch.encode("utf-8")
        if len(cur) + len(b) > (75 if not out else 74):
            out.append(cur.decode("utf-8"))
            cur = b""
        cur += b
    out.append(cur.decode("utf-8"))
    return "\r\n ".join(out)


def team_label(team: dict | None) -> str:
    if not team:
        return "TBD"
    return team.get("code") or team.get("name") or "TBD"


def team_matches(team: dict, wanted: set[str]) -> bool:
    return bool({(team.get("code") or "").lower(), (team.get("name") or "").lower()} & wanted)


def estimated_duration(best_of: int) -> dt.timedelta:
    # Rough broadcast lengths incl. draft & breaks; start times for later matches
    # on a day are estimates anyway and shift as the day runs.
    return dt.timedelta(minutes={1: 60, 3: 165, 5: 270}.get(best_of, 60 * best_of))


# -------------------------------------------------------------- build -----

def build_vevent(ev: dict, now: dt.datetime, *, alarm_minutes: int | None,
                 show_results: bool) -> list[str]:
    match = ev["match"]
    teams = (match.get("teams") or []) + [None, None]
    a, b = teams[0], teams[1]
    best_of = int((match.get("strategy") or {}).get("count") or 1)
    start = parse_time(ev["startTime"])
    end = start + estimated_duration(best_of)
    league = (ev.get("league") or {}).get("name", "LoL Esports")
    slug = (ev.get("league") or {}).get("slug", "worlds")
    stage = ev.get("blockName") or ""
    state = ev.get("state", "unstarted")

    la, lb = team_label(a), team_label(b)
    if show_results and state == "completed" and a and b:
        wa = (a.get("result") or {}).get("gameWins", 0)
        wb = (b.get("result") or {}).get("gameWins", 0)
        summary = f"{la} {wa}–{wb} {lb}"
    else:
        summary = f"{la} vs {lb}"
    summary += f" · {league}"

    desc = [f"{league}{' — ' + stage if stage else ''}", f"Best of {best_of}"]
    for t in (a, b):
        if t and t.get("name") and t.get("name") != "TBD":
            rec = t.get("record")
            rec_s = f" ({rec.get('wins', 0)}W–{rec.get('losses', 0)}L)" if rec else ""
            desc.append(f"{t['name']}{rec_s}")
    if la == "TBD" or lb == "TBD":
        desc.append("Teams TBD — this event updates automatically once they're decided.")
    if state == "completed" and not show_results:
        desc.append("Finished (result hidden to avoid spoilers).")
    desc.append("Start time is Riot's estimate and may shift on the day.")
    desc.append(f"Watch: https://lolesports.com/live/{slug}")
    desc.append("Also: twitch.tv/riotgames · youtube.com/@lolesports")

    lines = [
        "BEGIN:VEVENT",
        f"UID:{match['id']}@worlds-calendar",
        f"DTSTAMP:{ics_time(now)}",
        f"DTSTART:{ics_time(start)}",
        f"DTEND:{ics_time(end)}",
        f"SUMMARY:{ics_escape(summary)}",
        f"DESCRIPTION:{ics_escape(chr(10).join(desc))}",
        f"URL:https://lolesports.com/live/{slug}",
        f"CATEGORIES:{ics_escape(league)}",
        "TRANSP:TRANSPARENT",   # don't mark you as busy
        "STATUS:CONFIRMED",
    ]
    if alarm_minutes and start > now:
        lines += [
            "BEGIN:VALARM",
            "ACTION:DISPLAY",
            f"DESCRIPTION:{ics_escape(summary)}",
            f"TRIGGER:-PT{int(alarm_minutes)}M",
            "END:VALARM",
        ]
    lines.append("END:VEVENT")
    return lines


def build_calendar(events: list[dict], *, cal_name: str, teams_filter: set[str],
                   alarm_minutes: int | None, show_results: bool,
                   now: dt.datetime | None = None) -> tuple[str, int]:
    now = now or dt.datetime.now(dt.timezone.utc)
    since = now - dt.timedelta(days=LOOKBACK_DAYS)

    seen: dict[str, dict] = {}
    for ev in events:
        if ev.get("type") != "match" or not ev.get("match") or not ev.get("startTime"):
            continue
        if parse_time(ev["startTime"]) < since:
            continue
        if teams_filter and not any(t and team_matches(t, teams_filter)
                                    for t in ev["match"].get("teams") or []):
            continue
        seen[ev["match"]["id"]] = ev  # dedupe across pages; last write wins

    ordered = sorted(seen.values(), key=lambda e: e["startTime"])
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//worlds-calendar//LoL Esports//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{ics_escape(cal_name)}",
        "X-WR-CALDESC:Auto-updating LoL Esports match schedule",
        "REFRESH-INTERVAL;VALUE=DURATION:PT1H",
        "X-PUBLISHED-TTL:PT1H",
    ]
    for ev in ordered:
        lines += build_vevent(ev, now, alarm_minutes=alarm_minutes, show_results=show_results)
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(l) for l in lines) + "\r\n", len(ordered)


# --------------------------------------------------------------- main -----

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="worlds.ics", help="output .ics path")
    ap.add_argument("--fixture", help="read events from a saved getSchedule JSON instead of the API (testing)")
    args = ap.parse_args()

    slugs = [s.strip() for s in (os.environ.get("LEAGUES") or "worlds").split(",") if s.strip()]
    teams_filter = {t.strip().lower() for t in os.environ.get("TEAMS", "").split(",") if t.strip()}
    alarm = os.environ.get("ALARM_MINUTES", "").strip()
    alarm_minutes = int(alarm) if alarm.isdigit() and int(alarm) > 0 else None
    show_results = os.environ.get("SHOW_RESULTS", "").strip().lower() in {"1", "true", "yes"}
    default_name = "LoL Worlds" if slugs == ["worlds"] else "LoL Esports"
    cal_name = os.environ.get("CAL_NAME", "").strip() or default_name

    now = dt.datetime.now(dt.timezone.utc)
    events: list[dict] = []
    if args.fixture:
        with open(args.fixture, encoding="utf-8") as f:
            events = json.load(f)["data"]["schedule"]["events"]
    else:
        leagues = get_leagues()
        for slug in slugs:
            if slug not in leagues:
                print(f"Unknown league slug '{slug}'. Known: {', '.join(sorted(leagues))}", file=sys.stderr)
                return 2
            events += get_schedule_events(leagues[slug]["id"], now - dt.timedelta(days=LOOKBACK_DAYS))

    ics, count = build_calendar(events, cal_name=cal_name, teams_filter=teams_filter,
                                alarm_minutes=alarm_minutes, show_results=show_results, now=now)
    if count == 0 and not teams_filter:
        # Refuse to publish an empty calendar — keeps the last good feed online
        # if the API hiccups or changes.
        print("No matches found; not overwriting the feed.", file=sys.stderr)
        return 1

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="") as f:
        f.write(ics)
    print(f"Wrote {count} matches to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
