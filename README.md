# Worlds Calendar

A free, self-hosted auto-updating calendar of LoL Worlds matches for Apple Calendar (or Google/Outlook).

Every 2 hours GitHub pulls the official lolesports schedule, rebuilds `worlds.ics`, and hosts it on GitHub Pages. Your calendar subscribes to that link, so new matches, start-time changes and knockout teams (TBD → real teams) appear by themselves.

## Setup (about 5 minutes, one time)

1. **Create a repo.** On github.com → New repository → name it e.g. `worlds-calendar` → **Public** (free Pages needs public) → Create.
2. **Upload the files.** Easiest is from a terminal in this folder:
   ```bash
   git init -b main
   git add .
   git commit -m "Worlds calendar"
   git remote add origin https://github.com/<your-username>/worlds-calendar.git
   git push -u origin main
   ```
   *(Using the website instead? Upload `worlds_calendar.py`, `index.html` and `README.md`, then use **Add file → Create new file**, type the name `.github/workflows/update-calendar.yml` and paste that file's contents in. Finder hides the `.github` folder, which is why it needs doing separately.)*
3. **Turn on Pages.** Repo → **Settings → Pages → Source: GitHub Actions**.
4. **Run it once.** Repo → **Actions** → *Update calendar feed* → **Run workflow**. Wait for the green tick (~30 s).
5. **Subscribe.** On your iPhone, open `https://<your-username>.github.io/worlds-calendar/` in Safari and tap **Subscribe in Apple Calendar**.
   On a Mac: Calendar → File → New Calendar Subscription → paste `https://<your-username>.github.io/worlds-calendar/worlds.ics` → set **Auto-refresh: Every hour**.

That's it. It syncs to all your Apple devices via iCloud.

## Options

Repo → **Settings → Secrets and variables → Actions → Variables tab → New repository variable**. Then re-run the workflow.

| Variable | Example | What it does |
|---|---|---|
| `TEAMS` | `T1,G2` | Only those teams' matches. Blank = everything. Knockout matches appear once the team qualifies. |
| `ALARM_MINUTES` | `15` | Notification this many minutes before each match. |
| `SHOW_RESULTS` | `1` | Put scores in finished matches (off by default: no spoilers if you watch VODs). |
| `LEAGUES` | `worlds,msi,lec` | Track other leagues too. Slugs: worlds, msi, first_stand, lec, lck, lpl, lcs… |
| `CAL_NAME` | `Worlds 🏆` | Calendar name. |

## Good to know

- **Times** are stored in UTC and shown in your own time zone automatically. Later matches on a day are Riot's estimates and shift as the day runs; the feed tracks Riot's updates.
- **Refresh speed:** GitHub runs every ~2 hours (sometimes a little late at busy times); Apple Calendar then picks it up on its own refresh. Want it sooner? Actions → Run workflow.
- **If the schedule API ever hiccups**, the job fails instead of publishing an empty calendar, so your last good feed stays up.
- **After the tournament**, GitHub pauses scheduled jobs on repos with no activity for 60 days. For next year, just press Run workflow (or make any commit) to wake it up.
- **Testing locally:** `python3 worlds_calendar.py --out worlds.ics` then double-click the file.
