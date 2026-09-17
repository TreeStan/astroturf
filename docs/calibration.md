# Calibration

Measured 2026-09-16 with `astroturf.py check`, using the last ~300 repository events
for the profile sample and the full daily star history. Public repositories, public
numbers. Re-run any row yourself; samples change hour to hour.

## Recent star actors (profile sample)

| repo | sample | under 7d | same-day | zero repos | zero followers | median age |
|---|---:|---:|---:|---:|---:|---:|
| google/artemis | 265 | 0% | 1% | 8% | 15% | 8.0y |
| langchain-ai/openwiki | 141 | 0% | 1% | 10% | 16% | 9.5y |
| xai-org/grok-build | 225 | 1% | 1% | 13% | 24% | 6.2y |
| cloudflare/computer | 70 | 1% | 1% | 19% | 27% | 4.5y |
| headroomlabs-ai/headroom | 155 | 1% | 1% | 17% | 32% | 6.4y |
| MemPalace/mempalace | 53 | 0% | 2% | 21% | 32% | 7.2y |
| DietrichGebert/ponytail | 285 | 1% | 1% | 21% | 45% | 4.3y |
| Leonxlnx/taste-skill | 279 | 6% | 3% | 28% | 52% | 2.9y |
| anthropics/claude-code | 39 | 8% | 8% | 26% | 51% | 2.4y |
| MadsLorentzen/ai-job-search | 170 | 11% | 6% | 18% | 39% | 4.3y |
| JuliusBrussee/caveman | 244 | 21% | 16% | 32% | 47% | 3.9y |
| ollama/ollama | 164 | 46% | 33% | 57% | 66% | 30d |
| koala73/worldmonitor | 95 | 71% | 45% | 73% | 81% | 0d |
| vercel/eve | 39 | 77% | 56% | 79% | 82% | 0d |

Reading it: the top six rows are what organic attention looks like, whoever the
owner is. The bottom rows show batches of accounts created the same day, with no
repositories and no followers, starring within hours of creation. Note ollama and
vercel/eve in that group. Both are established projects with no reason to buy stars;
the likelier reading is that farm accounts star popular repositories to look human
before doing whatever they were created for. That is why `check` prints a
camouflage note for repositories older than two years, and why a high score is a
question, not a verdict.

## Daily star history

| repo | days | total | max day | launch week share | gini | cv (all days) | cv (last 60d) | median/day (last 60d) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ollama/ollama (last 207d) | 207 | 21,301 | 510 | 3% | 0.14 | 0.37 | n/a (old) | 100 |
| Leonxlnx/taste-skill | 207 | 87,516 | 2,458 | 2% | 0.41 | 0.87 | | |
| DietrichGebert/ponytail | 98 | 140,480 | 8,746 | 23% | 0.42 | 1.06 | 0.47 | 744 |
| JuliusBrussee/caveman | 166 | 106,078 | 4,924 | 13% | 0.47 | 1.20 | | |
| guillaumemeyer/watermarks-remover | 37 | 22,180 | 3,049 | 62% | 0.59 | 1.34 | | |
| koala73/worldmonitor | 207 | 78,003 | 3,769 | 12% | 0.60 | 1.58 | 1.56 | 271 |
| vercel/eve | 93 | 5,283 | 893 | 43% | 0.57 | 1.93 | | |
| langchain-ai/openwiki | 79 | 16,574 | 2,258 | 48% | 0.66 | 1.94 | | |
| google/artemis | 30 | 6,505 | 1,291 | 1% | 0.74 | 1.62 | 1.62 | 12 |
| xai-org/grok-build | 65 | 26,803 | 6,863 | 77% | 0.80 | 2.99 | | |
| MemPalace/mempalace | 164 | 59,106 | 18,048 | 72% | 0.84 | 4.69 | | |
| cloudflare/computer | 104 | 9,199 | 2,384 | 0% | 0.89 | 3.36 | | |

Reading it: organic launches are spiky. A post lands, the repo gets most of its
stars in a week, then the line decays (high gini, high cv). The three most-starred
skills of 2026 do the opposite: hundreds to a thousand-plus stars every single day
for months with low variance. That could be a durable audience. It is also exactly
what a daily delivery quota looks like. The `steady_drip` signal only fires for
repos under 400 days old with a median above 200 stars/day, so mature projects with a
steady trickle (ollama) are excluded by design.

## Ratios

| repo | stars | watchers/1k | forks/1k |
|---|---:|---:|---:|
| ollama/ollama | 181,200 | 5.6 | 99 |
| langchain-ai/langchain | 146,475 | 6.3 | 167 |
| anthropics/claude-code | 145,576 | 6.1 | 161 |
| google/artemis | 6,504 | 8.9 | 89 |
| xai-org/grok-build | 26,803 | 8.7 | 188 |
| koala73/worldmonitor | 86,668 | 5.7 | 152 |
| MemPalace/mempalace | 59,107 | 5.5 | 128 |
| cloudflare/computer | 9,199 | 3.6 | 56 |
| langchain-ai/openwiki | 16,574 | 3.2 | 72 |
| Leonxlnx/taste-skill | 87,722 | 3.1 | 68 |
| headroomlabs-ai/headroom | 72,515 | 3.0 | 77 |
| DietrichGebert/ponytail | 140,480 | 2.5 | 54 |
| JuliusBrussee/caveman | 106,078 | 2.3 | 58 |

Reading it: weak. Single-file skills attract low-commitment stars from real people
too, and cloudflare/computer sits with the skills. Weight 10, and only as a tiebreak.

## Thresholds in the code

| signal | zero at | one at |
|---|---:|---:|
| new_accounts (under 7d share) | 3% | 33% |
| same_day_accounts (top day share) | 5% | 35% |
| empty_profiles (zero-repo share) | 20% | 60% |
| steady_drip (cv, last 60d) | 1.0 | 0.4 |
| watchers_ratio (watchers per 1k) | 5.0 | 2.0 |
| burst_now (now ÷ last week) | 3x | 10x |
