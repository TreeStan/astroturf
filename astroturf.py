#!/usr/bin/env python3
"""astroturf: star-authenticity signals for GitHub repositories.

GitHub stopped exposing who starred a repository on 2026-06-30. This tool uses what
is still public: the daily star history endpoint (added 2026-09-04), the last 300
repository events (which include recent star actors), repository ratios, and the
public profiles of those recent actors. It turns them into explainable signals and a
0-100 score. A score is a bundle of signals, not proof of anything.

Usage:
    astroturf.py check OWNER/REPO [OWNER/REPO ...] [--json] [--no-profiles]
    astroturf.py trending [--query Q] [--created 90d] [--min-stars 1000] [--top 25]
                          [--out report.md] [--json] [--no-profiles]
    astroturf.py explain

Token: GITHUB_TOKEN env var, or `gh auth token` if the gh CLI is logged in.
Standard library only.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import os
import re
import ssl
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.github.com"
UA = "astroturf (https://github.com/TreeStan/astroturf)"
GQL_BATCH = 25          # more than ~40 aliased user lookups per query gets rejected
GQL_PAUSE = 4.0         # seconds between GraphQL calls; faster than this trips the secondary rate limit
DRIP_WINDOW_DAYS = 60
DRIP_MIN_DAILY = 200
DRIP_MAX_AGE_DAYS = 400

WEIGHTS = {
    "new_accounts": 25,
    "steady_drip": 25,
    "same_day_accounts": 20,
    "empty_profiles": 15,
    "watchers_ratio": 10,
    "burst_now": 5,
}

EXPLAIN = {
    "new_accounts": "Share of recent star actors whose GitHub account is under 7 days old. "
                    "Organic baseline is 0-2%. Rises to 20-80% when a farm is active on the repo.",
    "steady_drip": "For repos under 400 days old with 200+ stars/day: how flat the daily count "
                   "is over the last 60 days (low coefficient of variation). Organic attention "
                   "decays after a launch; purchased stars arrive as a daily quota.",
    "same_day_accounts": "Largest share of recent star actors created on one calendar day. "
                         "Baseline 1-3%. Farms create accounts in batches.",
    "empty_profiles": "Share of recent star actors with zero public repositories. Baseline 8-25%. "
                      "Farm accounts rarely have any.",
    "watchers_ratio": "Watchers per 1,000 stars. Established repos sit around 5-9; below 3 means "
                      "stars arrived without anyone caring enough to watch. Weak on its own.",
    "burst_now": "Stars per hour in the last ~300 events versus the last week's average. "
                 "Bursts are usually organic (a launch post), so this is a small weight.",
}


# ---------------------------------------------------------------- HTTP

class GitHub:
    def __init__(self, token: str | None = None, verbose: bool = False):
        self.token = token or os.environ.get("GITHUB_TOKEN") or gh_token()
        self.verbose = verbose
        self._ctx = ssl.create_default_context()
        try:
            import certifi  # type: ignore
            self._ctx = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            pass
        self._last_gql = 0.0

    def _headers(self, extra: dict | None = None) -> dict:
        h = {"User-Agent": UA, "Accept": "application/vnd.github+json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        h.update(extra or {})
        return h

    def get(self, path: str, ok404: bool = False):
        url = path if path.startswith("http") else API + path
        req = urllib.request.Request(url, headers=self._headers())
        for attempt in range(4):
            try:
                with urllib.request.urlopen(req, timeout=60, context=self._ctx) as r:
                    return json.loads(r.read() or b"null")
            except urllib.error.HTTPError as e:
                if e.code == 404 and ok404:
                    return None
                if e.code in (403, 429) and attempt < 3:
                    wait = int(e.headers.get("Retry-After") or 30 * (attempt + 1))
                    self._log(f"HTTP {e.code} on {path}; waiting {wait}s")
                    time.sleep(wait)
                    continue
                body = e.read().decode(errors="replace")[:200]
                raise SystemExit(f"GET {path} -> HTTP {e.code}: {body}")
            except urllib.error.URLError as e:
                if "CERTIFICATE_VERIFY_FAILED" in str(e):
                    return self._via_gh(path)
                raise
        raise SystemExit(f"GET {path}: gave up")

    def _via_gh(self, path: str):
        """python.org builds on macOS ship without CA certs; fall back to the gh CLI."""
        r = subprocess.run(["gh", "api", path.replace(API, "")], capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit("TLS verification failed and gh fallback failed: pip install certifi")
        return json.loads(r.stdout)

    def graphql(self, query: str) -> dict:
        gap = GQL_PAUSE - (time.time() - self._last_gql)
        if gap > 0:
            time.sleep(gap)
        req = urllib.request.Request(API + "/graphql", data=json.dumps({"query": query}).encode(),
                                     headers=self._headers({"Content-Type": "application/json"}))
        for attempt in range(5):
            try:
                with urllib.request.urlopen(req, timeout=60, context=self._ctx) as r:
                    self._last_gql = time.time()
                    return json.loads(r.read())
            except urllib.error.HTTPError as e:
                if e.code in (403, 429):
                    wait = int(e.headers.get("Retry-After") or 60)
                    self._log(f"GraphQL secondary rate limit; waiting {wait}s")
                    time.sleep(wait)
                    continue
                raise SystemExit(f"GraphQL HTTP {e.code}: {e.read().decode(errors='replace')[:200]}")
        raise SystemExit("GraphQL: gave up after rate limits")

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(f"  [{msg}]", file=sys.stderr)


def gh_token() -> str | None:
    try:
        r = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, timeout=10)
        return r.stdout.strip() or None
    except (OSError, subprocess.TimeoutExpired):
        return None


# ---------------------------------------------------------------- data fetch

def fetch_repo(gh: GitHub, full: str) -> dict:
    return gh.get(f"/repos/{full}")


def fetch_history(gh: GitHub, full: str, max_pages: int = 100) -> list[int]:
    """Daily star counts, oldest first, with pre-creation zeros and future days trimmed."""
    weeks: list[dict] = []
    for page in range(1, max_pages + 1):
        chunk = gh.get(f"/repos/{full}/stargazers/history?per_page=30&page={page}", ok404=True)
        if not chunk:
            break
        weeks += chunk
        if len(chunk) < 30:
            break
    days = [d for w in sorted(weeks, key=lambda w: w["week"]) for d in w["days"]]
    while days and days[0] == 0:
        days.pop(0)
    while days and days[-1] == 0:
        days.pop()
    return days


def fetch_recent_star_actors(gh: GitHub, full: str) -> list[tuple[str, str]]:
    """(login, created_at) for WatchEvents in the last ~300 repo events."""
    out: list[tuple[str, str]] = []
    for page in (1, 2, 3):
        events = gh.get(f"/repos/{full}/events?per_page=100&page={page}", ok404=True)
        if not events:
            break
        out += [(e["actor"]["login"], e["created_at"]) for e in events if e.get("type") == "WatchEvent"]
        if len(events) < 100:
            break
    return out


def fetch_profiles(gh: GitHub, logins: list[str], limit: int = 150) -> list[dict]:
    logins = list(dict.fromkeys(logins))[:limit]
    users: list[dict] = []
    for i in range(0, len(logins), GQL_BATCH):
        chunk = logins[i:i + GQL_BATCH]
        q = "{" + " ".join(
            f'u{j}: user(login:"{login}"){{login createdAt followers{{totalCount}} following{{totalCount}} '
            f'repositories{{totalCount}} starredRepositories{{totalCount}}}}'
            for j, login in enumerate(chunk) if re.fullmatch(r"[A-Za-z0-9-]+", login)) + "}"
        data = gh.graphql(q).get("data") or {}
        users += [u for u in data.values() if u]
    return users


# ---------------------------------------------------------------- signals (pure)

def clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def signal_new_accounts(profiles: list[dict], now: dt.datetime) -> tuple[float, dict]:
    if not profiles:
        return 0.0, {"note": "no profiles"}
    ages = [(now - parse_ts(u["createdAt"])).days for u in profiles]
    n = len(ages)
    new7 = sum(a < 7 for a in ages) / n
    new30 = sum(a < 30 for a in ages) / n
    return clamp((new7 - 0.03) / 0.30), {"under_7d": new7, "under_30d": new30,
                                          "median_age_days": int(statistics.median(ages)), "n": n}


def signal_same_day(profiles: list[dict]) -> tuple[float, dict]:
    if not profiles:
        return 0.0, {"note": "no profiles"}
    days = collections.Counter(u["createdAt"][:10] for u in profiles)
    top_day, top_n = days.most_common(1)[0]
    share = top_n / len(profiles)
    return clamp((share - 0.05) / 0.30), {"top_day": top_day, "top_day_share": share}


def signal_empty_profiles(profiles: list[dict]) -> tuple[float, dict]:
    if not profiles:
        return 0.0, {"note": "no profiles"}
    n = len(profiles)
    zero_repos = sum(u["repositories"]["totalCount"] == 0 for u in profiles) / n
    zero_followers = sum(u["followers"]["totalCount"] == 0 for u in profiles) / n
    return clamp((zero_repos - 0.20) / 0.40), {"zero_repos": zero_repos, "zero_followers": zero_followers}


def signal_watchers_ratio(repo: dict) -> tuple[float, dict]:
    stars = repo.get("stargazers_count") or 0
    subs = repo.get("subscribers_count") or 0
    if stars < 500:
        return 0.0, {"note": "too few stars"}
    per_1k = 1000 * subs / stars
    return clamp((5.0 - per_1k) / 3.0), {"watchers_per_1k": per_1k, "forks_per_1k": 1000 * (repo.get("forks_count") or 0) / stars}


def signal_steady_drip(days: list[int], age_days: int) -> tuple[float, dict]:
    if len(days) < 21 or age_days > DRIP_MAX_AGE_DAYS:
        return 0.0, {"note": "not applicable (needs 3+ weeks of history and age under 400 days)"}
    window = days[-DRIP_WINDOW_DAYS:]
    med = statistics.median(window)
    mean = statistics.mean(window)
    cv = statistics.pstdev(window) / mean if mean else 0.0
    info = {"window_days": len(window), "median_daily": med, "cv": cv, "total": sum(days),
            "max_day": max(days), "launch_week_share": sum(days[:7]) / max(sum(days), 1)}
    if med < DRIP_MIN_DAILY:
        info["note"] = f"median daily {med:.0f} below {DRIP_MIN_DAILY}; drip check not applied"
        return 0.0, info
    return clamp((1.0 - cv) / 0.6), info


def signal_burst_now(actors: list[tuple[str, str]], days: list[int]) -> tuple[float, dict]:
    if len(actors) < 20 or len(days) < 7:
        return 0.0, {"note": "not enough events"}
    ts = sorted(parse_ts(t) for _, t in actors)
    hours = max((ts[-1] - ts[0]).total_seconds() / 3600, 0.25)
    rate_now = len(actors) / hours
    rate_week = sum(days[-7:]) / (7 * 24)
    ratio = rate_now / rate_week if rate_week else 0.0
    return clamp((ratio - 3.0) / 7.0), {"stars_per_hour_now": rate_now, "stars_per_hour_week": rate_week, "ratio": ratio}


def score(signals: dict[str, float]) -> float:
    return round(sum(WEIGHTS[k] * v for k, v in signals.items()), 1)


def label(s: float) -> str:
    if s < 20:
        return "looks organic"
    if s < 40:
        return "some signals"
    if s < 65:
        return "strong signals"
    return "very strong signals"


def parse_ts(s: str) -> dt.datetime:
    return dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- analysis

def analyze(gh: GitHub, full: str, profiles: bool = True, now: dt.datetime | None = None) -> dict:
    now = now or dt.datetime.utcnow()
    repo = fetch_repo(gh, full)
    days = fetch_history(gh, full)
    actors = fetch_recent_star_actors(gh, full)
    users = fetch_profiles(gh, [a for a, _ in actors]) if profiles and actors else []
    return assemble(full, repo, days, actors, users, now)


def assemble(full: str, repo: dict, days: list[int], actors: list, users: list[dict], now: dt.datetime) -> dict:
    age = (now - parse_ts(repo["created_at"])).days
    sig: dict[str, float] = {}
    info: dict[str, dict] = {}
    sig["new_accounts"], info["new_accounts"] = signal_new_accounts(users, now)
    sig["same_day_accounts"], info["same_day_accounts"] = signal_same_day(users)
    sig["empty_profiles"], info["empty_profiles"] = signal_empty_profiles(users)
    sig["watchers_ratio"], info["watchers_ratio"] = signal_watchers_ratio(repo)
    sig["steady_drip"], info["steady_drip"] = signal_steady_drip(days, age)
    sig["burst_now"], info["burst_now"] = signal_burst_now(actors, days)
    total = score(sig)
    notes = []
    if age > 730 and sig["new_accounts"] > 0.3:
        notes.append("Repo is over two years old: new-account stars here more often mean farm accounts "
                     "using a popular repo as camouflage than stars bought by the owner.")
    if not users:
        notes.append("No profile sample (profiles disabled or no recent star events); score uses history and ratios only.")
    if len(users) < 50 and users:
        notes.append(f"Profile sample is small ({len(users)}); treat profile signals as rough.")
    return {
        "repo": full, "stars": repo.get("stargazers_count"), "forks": repo.get("forks_count"),
        "watchers": repo.get("subscribers_count"), "open_issues": repo.get("open_issues_count"),
        "age_days": age, "created_at": repo["created_at"],
        "recent_star_events": len(actors), "profiles_sampled": len(users),
        "signals": sig, "details": info, "score": total, "label": label(total), "notes": notes,
        "checked_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


# ---------------------------------------------------------------- output

def fmt_pct(x) -> str:
    return f"{100 * x:.0f}%" if isinstance(x, (int, float)) else "-"


def render_check(r: dict) -> str:
    d = r["details"]
    lines = [f"{r['repo']}  {r['stars']:,} stars  {r['age_days']}d old  score {r['score']}  ({r['label']})", ""]
    lines.append(f"  {'signal':<20}{'weight':>7}{'value':>7}   evidence")
    rows = [
        ("new_accounts", f"{fmt_pct(d['new_accounts'].get('under_7d'))} of {d['new_accounts'].get('n', 0)} recent star actors under 7 days old"
                         + (f", median age {d['new_accounts']['median_age_days']}d" if 'median_age_days' in d['new_accounts'] else "")),
        ("steady_drip", (f"median {d['steady_drip']['median_daily']:.0f}/day, cv {d['steady_drip']['cv']:.2f} over last {d['steady_drip']['window_days']}d"
                         if "cv" in d["steady_drip"] else d["steady_drip"].get("note", ""))),
        ("same_day_accounts", f"{fmt_pct(d['same_day_accounts'].get('top_day_share'))} created on {d['same_day_accounts'].get('top_day', '-')}"),
        ("empty_profiles", f"{fmt_pct(d['empty_profiles'].get('zero_repos'))} zero repos, {fmt_pct(d['empty_profiles'].get('zero_followers'))} zero followers"),
        ("watchers_ratio", f"{d['watchers_ratio'].get('watchers_per_1k', 0):.1f} watchers per 1k stars" if "watchers_per_1k" in d["watchers_ratio"] else d["watchers_ratio"].get("note", "")),
        ("burst_now", f"{d['burst_now']['stars_per_hour_now']:.0f}/h now vs {d['burst_now']['stars_per_hour_week']:.0f}/h last week" if "ratio" in d["burst_now"] else d["burst_now"].get("note", "")),
    ]
    for k, ev in rows:
        lines.append(f"  {k:<20}{WEIGHTS[k]:>7}{r['signals'][k]:>7.2f}   {ev}")
    for n in r["notes"]:
        lines.append(f"  note: {n}")
    return "\n".join(lines)


def render_leaderboard(results: list[dict], query: str, now: dt.datetime) -> str:
    by_stars = sorted(results, key=lambda r: -(r["stars"] or 0))
    for i, r in enumerate(by_stars, 1):
        r["rank_raw"] = i
        r["discounted"] = int((r["stars"] or 0) * (1 - r["score"] / 100))
    by_adj = sorted(results, key=lambda r: -r["discounted"])
    for i, r in enumerate(by_adj, 1):
        r["rank_adj"] = i
    out = [f"# Trending, adjusted for astroturf signals", "",
           f"Generated {now:%Y-%m-%d %H:%M} UTC. Query: `{query}`. {len(results)} repos.", "",
           "**Read this first.** The score bundles public signals (new accounts among recent star actors, "
           "accounts created in batches, empty profiles, a flat daily star drip, watcher ratio). It is not "
           "evidence that anyone bought anything. A repo can score high because a farm used it as camouflage, "
           "because a bootcamp told 300 new accounts to star it, or because it is genuinely popular with "
           "newcomers. Every number here is reproducible with `astroturf.py check OWNER/REPO`.", "",
           "| adj | raw | repo | stars | score | label | new accts | same day | zero repos | drip cv | watchers/1k |",
           "|---:|---:|---|---:|---:|---|---:|---:|---:|---:|---:|"]
    for r in by_adj:
        d = r["details"]
        cv = d["steady_drip"].get("cv")
        out.append(
            f"| {r['rank_adj']} | {r['rank_raw']} | [{r['repo']}](https://github.com/{r['repo']}) | {r['stars']:,} | "
            f"{r['score']} | {r['label']} | {fmt_pct(d['new_accounts'].get('under_7d'))} | "
            f"{fmt_pct(d['same_day_accounts'].get('top_day_share'))} | {fmt_pct(d['empty_profiles'].get('zero_repos'))} | "
            f"{cv:.2f} | {d['watchers_ratio'].get('watchers_per_1k', 0):.1f} |" if cv is not None else
            f"| {r['rank_adj']} | {r['rank_raw']} | [{r['repo']}](https://github.com/{r['repo']}) | {r['stars']:,} | "
            f"{r['score']} | {r['label']} | {fmt_pct(d['new_accounts'].get('under_7d'))} | "
            f"{fmt_pct(d['same_day_accounts'].get('top_day_share'))} | {fmt_pct(d['empty_profiles'].get('zero_repos'))} | "
            f"- | {d['watchers_ratio'].get('watchers_per_1k', 0):.1f} |")
    out += ["", "Columns: *new accts* = share of recent star actors under 7 days old; *same day* = largest share "
            "created on one day; *zero repos* = share with no public repos; *drip cv* = coefficient of variation "
            "of daily stars over the last 60 days (lower is flatter); *watchers/1k* = watchers per 1,000 stars.", "",
            "Weights: " + ", ".join(f"{k} {v}" for k, v in WEIGHTS.items()) + ".", ""]
    return "\n".join(out)


# ---------------------------------------------------------------- commands

def cmd_check(gh: GitHub, a) -> int:
    results = []
    for full in a.repos:
        if a.verbose:
            print(f"checking {full}", file=sys.stderr)
        results.append(analyze(gh, full, profiles=not a.no_profiles))
    if a.json:
        print(json.dumps(results if len(results) > 1 else results[0], indent=2))
    else:
        print("\n\n".join(render_check(r) for r in results))
    return 0


def parse_span(s: str) -> int:
    m = re.fullmatch(r"(\d+)([dwmy])", s)
    if not m:
        raise SystemExit("--created wants e.g. 90d, 12w, 6m, 1y")
    n, u = int(m.group(1)), m.group(2)
    return n * {"d": 1, "w": 7, "m": 30, "y": 365}[u]


def cmd_trending(gh: GitHub, a) -> int:
    now = dt.datetime.utcnow()
    since = (now - dt.timedelta(days=parse_span(a.created))).strftime("%Y-%m-%d")
    query = a.query or f"created:>={since} stars:>={a.min_stars}"
    per_page = min(a.top, 100)
    items = gh.get(f"/search/repositories?q={urllib.parse.quote(query)}&sort=stars&order=desc&per_page={per_page}")["items"][:a.top]
    results = []
    for i, it in enumerate(items, 1):
        full = it["full_name"]
        if a.verbose:
            print(f"[{i}/{len(items)}] {full}", file=sys.stderr)
        try:
            results.append(analyze(gh, full, profiles=not a.no_profiles, now=now))
        except SystemExit as e:
            print(f"skipping {full}: {e}", file=sys.stderr)
    if a.json:
        print(json.dumps(results, indent=2))
        return 0
    md = render_leaderboard(results, query, now)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"wrote {a.out}")
    else:
        print(md)
    return 0


def cmd_explain(_gh, _a) -> int:
    print("astroturf score = sum(weight x signal), each signal 0..1\n")
    for k, w in WEIGHTS.items():
        print(f"{k} ({w})\n  {EXPLAIN[k]}\n")
    print("Labels: <20 looks organic, 20-39 some signals, 40-64 strong signals, 65+ very strong signals.")
    print("Nothing here is proof. See README 'What this cannot tell you'.")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--token", help="GitHub token (default: GITHUB_TOKEN or gh auth token)")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("check"); p.add_argument("repos", nargs="+"); p.add_argument("--json", action="store_true"); p.add_argument("--no-profiles", action="store_true")
    p = sub.add_parser("trending"); p.add_argument("--query"); p.add_argument("--created", default="90d"); p.add_argument("--min-stars", type=int, default=1000)
    p.add_argument("--top", type=int, default=25); p.add_argument("--out"); p.add_argument("--json", action="store_true"); p.add_argument("--no-profiles", action="store_true")
    sub.add_parser("explain")
    a = ap.parse_args(argv)
    if a.cmd == "explain":
        return cmd_explain(None, a)
    gh = GitHub(a.token, verbose=a.verbose)
    if not gh.token:
        print("warning: no token; unauthenticated limits are 60 requests/hour and GraphQL is unavailable", file=sys.stderr)
    return {"check": cmd_check, "trending": cmd_trending}[a.cmd](gh, a)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
