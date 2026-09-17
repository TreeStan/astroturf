<p align="center">
  <img src="assets/icon.png" width="128" height="128" alt="astroturf icon">
</p>

<h1 align="center">astroturf</h1>

<p align="center">
  GitHub trending, adjusted for stars that look bought.<br>
  Public data, explainable signals, a 0-100 score, and a weekly leaderboard that names names.
</p>

<p align="center">
  <a href="https://github.com/TreeStan/astroturf/actions/workflows/ci.yml"><img src="https://github.com/TreeStan/astroturf/actions/workflows/ci.yml/badge.svg" alt="ci"></a>
  <a href="reports/latest.md"><img src="https://img.shields.io/badge/leaderboard-weekly-brightgreen.svg" alt="weekly leaderboard"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="MIT"></a>
  <img src="https://img.shields.io/badge/deps-none-success.svg" alt="no dependencies">
</p>

---

**[This week's leaderboard →](reports/latest.md)**

On 2026-06-30 GitHub stopped showing who starred a repository. Star counts kept
climbing, and the tools that used to sanity-check them (star-history, the
stargazers page, every "fake star detector" that read the stargazer list) went dark.
On 2026-09-04 GitHub added a daily star history endpoint. The last 300 events of any
repository still name the accounts that starred it. Account profiles are still
public. That is enough to ask a useful question about any repo:

> Do the stars look like people found it, or like someone paid for a quota?

astroturf asks it with six signals and prints the evidence for each. Nothing here is
proof. Read [What this cannot tell you](#what-this-cannot-tell-you) before you post
a screenshot.

## Install

One file, standard library only, Python 3.9+.

```bash
curl -O https://raw.githubusercontent.com/TreeStan/astroturf/main/astroturf.py
export GITHUB_TOKEN=...      # or be logged in with the gh CLI; the token is picked up automatically
```

A token with no scopes is enough. Without one you get 60 requests an hour and no
profile signals.

## Use

```bash
python3 astroturf.py check koala73/worldmonitor
```

```
koala73/worldmonitor  86,676 stars  251d old  score 60.0  (strong signals)

  signal               weight  value   evidence
  new_accounts             25   1.00   73% of 93 recent star actors under 7 days old, median age 0d
  steady_drip              25   0.00   median 271/day, cv 1.56 over last 60d
  same_day_accounts        20   1.00   46% created on 2026-09-16
  empty_profiles           15   1.00   76% zero repos, 86% zero followers
  watchers_ratio           10   0.00   5.7 watchers per 1k stars
  burst_now                 5   0.00   10/h now vs 5/h last week
```

```bash
python3 astroturf.py check google/artemis          # 0.0, looks organic
python3 astroturf.py check DietrichGebert/ponytail # 31.2, some signals: 744 stars/day, every day, cv 0.47
python3 astroturf.py check a/b c/d --json          # machine-readable, all evidence included
python3 astroturf.py trending --created 120d --min-stars 3000 --top 30 --out report.md
python3 astroturf.py explain
```

`trending` searches GitHub for the most-starred repos in the window, scores each, and
writes a Markdown table with the raw rank, the adjusted rank, and every signal. A
GitHub Action in this repo runs it every Monday and commits the result to
`reports/`. Fork the repo and the leaderboard is yours.

## The signals

| signal | weight | what it measures | organic baseline | what farms look like |
|---|---:|---|---|---|
| new_accounts | 25 | share of recent star actors whose account is under 7 days old | 0-2% | 20-80% |
| steady_drip | 25 | flatness (coefficient of variation) of daily stars over the last 60 days, for repos under 400 days old with a median above 200 stars/day | organic attention decays after a launch, cv 1.5-4.7 | a delivered quota is flat, cv 0.4-0.9 |
| same_day_accounts | 20 | largest share of recent star actors created on one calendar day | 1-3% | 15-55% |
| empty_profiles | 15 | share of recent star actors with zero public repositories | 8-25% | 55-80% |
| watchers_ratio | 10 | watchers per 1,000 stars | 5-9 | 2-3, but single-file repos get there honestly too |
| burst_now | 5 | stars per hour in the last ~300 events versus last week's average | launches burst | launches burst too, hence the small weight |

Each signal is scaled to 0-1 between the baseline and the farm value, then weighted.
Labels: under 20 *looks organic*, 20-39 *some signals*, 40-64 *strong signals*, 65 and
up *very strong signals*. The numbers behind the baselines are in
[docs/calibration.md](docs/calibration.md), measured on 14 repos on 2026-09-16.

## What this cannot tell you

- **Who paid.** A high `new_accounts` or `same_day_accounts` score means farm-shaped
  accounts starred the repo recently. Farms star popular repositories to make their
  accounts look human before they spam. `ollama/ollama` scores on those signals for
  that reason, and nobody at Ollama bought anything. `check` prints a note when the
  repo is old enough for this reading to be the likelier one.
- **Whether a flat line is a quota or an audience.** `steady_drip` fires on repos
  that gain hundreds of stars every day for months without decay. A tool that every
  new coding-agent user installs on day one could do that. A daily delivery from a
  vendor does exactly that. The signal says "this is unusual", not which one.
- **Anything about the last 300 events beyond the last 300 events.** The profile
  sample is what GitHub still exposes: a few hours for a hot repo, a week for a quiet
  one. It is a sample of *now*.
- **Stars from before the sample.** History gives counts per day, not accounts. A
  repo that bought 50,000 stars in March and stopped will only show the drip if it is
  still dripping.

If you post a leaderboard, post the methodology with it. The table already includes
the raw evidence for every row; keep it there.

## How it works

1. `GET /repos/{owner}/{repo}` for stars, watchers, forks, age.
2. `GET /repos/{owner}/{repo}/stargazers/history` for daily counts back to creation.
3. `GET /repos/{owner}/{repo}/events` (3 pages, the cap) for recent `WatchEvent` actors.
4. One GraphQL query per 25 actors (up to 150 actors) for `createdAt`, followers, following, repositories,
   starred count. Paced at one query every four seconds; GitHub's secondary rate limit
   rejects faster batches and larger alias lists.
5. Pure functions turn those into signals; `assemble()` scores and labels.

About 4 REST calls and up to 6 GraphQL calls per repo. A 30-repo leaderboard takes
five to ten minutes because of the GraphQL pacing, and fits comfortably in the
5,000/hour budget of a personal token.

## Privacy

The tool never prints or stores account names. Reports carry aggregates only. The
`--json` output includes the sample size and the top creation day, not who was
created on it. This is deliberate: GitHub restricted the stargazer list because it
was being scraped for spam, and a tool built to audit stars should not become a
scraper.

## Contributing

Calibration rows beat opinions. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE)
