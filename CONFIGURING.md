# Configuring the AI News Briefing

All settings live in one file: **`.env`** (next to `brief.py`, permissions `600`).
You never need to edit it by hand — use **`./configure.py`**, which validates
input, preserves comments, and keeps a one-generation backup at `.env.bak`.

```bash
cd ~/ai-news-briefing

./configure.py                 # walk through every setting (Enter = keep current)
./configure.py --show          # see current config, secrets masked
./configure.py --email         # just the email section
./configure.py --llm           # just the model endpoint
./configure.py --briefing      # just the briefing behaviour
./configure.py --set KEY=VALUE # change one thing, no prompts (repeatable)
./configure.py --use-ollama    # switch to a local Ollama model
./configure.py --use-ollama-cloud gpt-oss:120b   # switch to Ollama Cloud
./configure.py --test-llm      # verify the model endpoint answers
./configure.py --test-email    # send a small test message
./configure.py --schedule 10:00  # change the daily run time (or `off`)
```

Environment variables override `.env`, so `MAIL_TO=x@y.com ./run.sh` works for a
one-off without changing anything permanently.

---

## Common changes

### Change who receives the briefing
```bash
./configure.py --set MAIL_TO=someone@example.com
./configure.py --test-email          # confirm it arrives
```
Several recipients: comma-separate them —
`./configure.py --set MAIL_TO="a@x.com,b@y.com"`

### Move to a local model (Ollama) — no API key, no quota
```bash
ollama pull gemma4:26b                      # once; ~17 GB
./configure.py --use-ollama gemma4:26b      # sets provider + URL + model, clears the key
./configure.py --test-llm
```
`--use-ollama` with no model argument keeps your current `LLM_MODEL` if it's
installed, else picks the first model the server reports. It also lists what's
pulled, and refuses a model you haven't pulled instead of failing mid-run.

An Ollama server on another machine works the same way:
```bash
./configure.py --set LLM_PROVIDER=ollama --set LLM_BASE_URL=http://gpu-box:11434 \
               --set LLM_MODEL=gemma4:26b --test-llm
```
(That server needs `OLLAMA_HOST=0.0.0.0:11434` to accept remote calls.)

### Move to Ollama Cloud (hosted, no GPU needed)
```bash
# key from https://ollama.com/settings/keys
./configure.py --set LLM_API_KEY=<key> --use-ollama-cloud gpt-oss:120b
./configure.py --test-llm
```
It's the same native `/api/chat`, so only the base URL, key and model change.
The run then needs almost nothing locally — enough CPU to parse feeds and
render a PDF — which is why a 16 GB N100 mini PC is plenty.

What changes automatically when the host is `ollama.com`:

| | local server | cloud |
|---|---|---|
| `keep_alive` | sent | not sent (no resident weights) |
| `LLM_STARTUP_WAIT` | waits for the service | skipped |
| `LLM_CONCURRENCY` default | `1` (one GPU) | `CONCURRENCY` (parallel is fine) |
| `LLM_TIMEOUT` default | `900` | `300` |
| Model not in `/api/tags` | hard error | warning, tries anyway |

Rate limits come back as HTTP 429 and are retried with backoff; if you hit them
often, lower `LLM_CONCURRENCY` or `PER_FEED_LIMIT`.

### Tune a local model
```bash
./configure.py --set LLM_NUM_CTX=16384      # bigger window (more RAM per call)
./configure.py --set LLM_TIMEOUT=1800       # very slow box / very long replies
./configure.py --set LLM_CONCURRENCY=2      # only if the GPU has headroom for 2 contexts
./configure.py --set LLM_KEEP_ALIVE=-1      # never unload the weights
./configure.py --set LLM_THINK=true         # thinking models; slower, rarely better here
```
`LLM_NUM_CTX` must cover `MAX_CONTENT_CHARS`/4 tokens plus ~800 for the prompt —
at the default 12 000 chars that's ~3 800, comfortably inside 8192. Raise the
window *or* lower `MAX_CONTENT_CHARS`; if the window is too small Ollama
truncates the article silently and the summaries get vague.

num_ctx covers the reply too, so a call that asks for 8000 tokens back needs
room for both. The weekly skills analysis does exactly that, and would overflow
8192 — so a call that doesn't fit gets a bigger window automatically (logged as
`growing context to N`), up to `LLM_MAX_NUM_CTX`. Ollama reloads the model when
the window changes, which costs a minute once a week; the ~90 article calls all
share the configured window and never reload. Lower the cap if the extra KV
cache pushes the box into swap.

A full run is ~90 article calls, one at a time. Ballpark at 26B/Q4 on a
consumer GPU: 25-45 s each, so 40-70 minutes. To speed it up: a smaller model,
`PER_FEED_LIMIT=5`, or `MAX_CONTENT_CHARS=8000` (prompt processing dominates).

### Rotate the LLM API key (gateway backends)
```bash
./configure.py --set LLM_API_KEY=sk-newkey... --test-llm
```
Or `./configure.py --llm` to be prompted (the key is hidden as you type).

### Switch model, or move to a different provider/gateway
```bash
# same backend, different model
./configure.py --set LLM_MODEL=gemma4:6b --test-llm

# hosted gateway instead of the local model
./configure.py --set LLM_PROVIDER=openai \
               --set LLM_BASE_URL=https://api.openai.com/v1 \
               --set LLM_API_KEY=sk-... \
               --set LLM_MODEL=gpt-4o --test-llm
```
With `LLM_PROVIDER=openai`, any **OpenAI-compatible** `/chat/completions`
endpoint works — OpenAI, OpenRouter, vLLM, llama.cpp, a corporate gateway.
`LLM_BASE_URL` should end in `/v1`; the script appends `/chat/completions`.
With `LLM_PROVIDER=ollama` the base URL is the server root (no `/v1`) and the
script uses the native `/api/chat`, which is the only way to set `num_ctx`.

### Change the email account it sends from
```bash
./configure.py --email          # prompts for host, port, security, user, password
./configure.py --test-email
```
Gmail needs a **16-character App Password**, not your normal login password
(Google Account → Security → 2-Step Verification → App passwords). Ports:
`465` with `SMTP_SECURITY=ssl`, or `587` with `starttls`.

### Change the schedule
```bash
./configure.py --schedule 07:30     # daily at 07:30 local time
./configure.py --schedule off       # stop the automatic run
crontab -l                          # see what's scheduled
```
Cron uses **local time**, so `10:00` means 10:00 wherever the box thinks it
is. On a new machine set the zone first:
`sudo timedatectl set-timezone Asia/Kolkata` (or your own `Area/City`).

### Change which sources are read
By default it uses the bundled 25-source AI preset in `sources.py`.
To override with your own list:
```bash
./configure.py --set SOURCES="https://openai.com/news/rss.xml,https://techcrunch.com/category/artificial-intelligence/feed/"
./configure.py --set SOURCES=          # back to the bundled preset
```
Feed URLs, article URLs, or plain site URLs all work — feeds are auto-discovered.
To permanently add a source to the preset, edit `AI_NEWS_SOURCES` in `sources.py`.

### Make the briefing shorter, longer, or narrower
```bash
./configure.py --set WINDOW_HOURS=12       # last 12h instead of 24
./configure.py --set PER_FEED_LIMIT=5      # fewer articles per source (faster, cheaper)
./configure.py --set DETAIL_LIMIT=10       # 10 full cards; rest as a compact list
./configure.py --set KEYWORDS="agents,inference,open source"   # only matching items
./configure.py --set KEYWORDS=             # remove the filter
```

### PDF archive
```bash
./configure.py --set SAVE_PDF=false          # stop saving PDFs
./configure.py --set PDF_DIR=~/briefings     # keep them elsewhere
./configure.py --set ATTACH_PDF=true         # attach the PDF to the email too
```
Files are named `AI_News_Briefing_<date>_<HHMM>.pdf`. They're gitignored, and
nothing prunes them — delete old ones yourself if they pile up.

### Weekly skills gap / your CV
```bash
./configure.py --set CV_PATH=~/docs/my_cv.pdf   # default is cv.pdf in this folder
./skills.py refresh-cv                       # re-read it after an update
./configure.py --set SKILLS_WINDOW_DAYS=14   # analyse 14 days of news instead of 7
./configure.py --set MAX_SKILL_GAPS=5        # shorter list
./configure.py --schedule 10:00 --weekly-day 6   # run the skills analysis on Saturday
```
Mark things off as you learn them so they stop being suggested:
```bash
./skills.py learned "vLLM / SGLang serving"
./skills.py dismiss "Mojo"        # never suggest this one
./skills.py show                  # what's known, learned, and still open
```
The CV must be a **text** PDF — a scanned image won't extract (the tool says so
rather than silently producing nothing).

### If the gateway rate-limits you (HTTP 429)
The run already retries with backoff. If it's still noisy, slow it down:
```bash
./configure.py --set CONCURRENCY=2 --set LLM_MAX_RETRIES=6
```

---

## Every setting

| Key | Default | What it does |
|---|---|---|
| `MAIL_TO` | — | Recipient(s), comma-separated |
| `MAIL_FROM` | `SMTP_USER` | From address |
| `SMTP_HOST` | — | e.g. `smtp.gmail.com` |
| `SMTP_PORT` | `465` | `465` (ssl) or `587` (starttls) |
| `SMTP_SECURITY` | `ssl` | `ssl` \| `starttls` \| `plain` |
| `SMTP_USER` | — | Usually the full email address |
| `SMTP_PASS` | — | App password for Gmail |
| `LLM_PROVIDER` | `auto` | `ollama` \| `openai` \| `auto` (sniffs the URL) |
| `LLM_BASE_URL` | `http://localhost:11434` | Ollama root, or OpenAI-compatible base ending `/v1` |
| `LLM_API_KEY` | — | Sent as `Authorization: Bearer <key>`; needed for Ollama Cloud, unused for a local server |
| `LLM_MODEL` | `gemma4:26b` | Model id / Ollama tag |
| `LLM_NUM_CTX` | `8192` | Ollama context window (tokens) |
| `LLM_MAX_NUM_CTX` | `32768` | Ceiling when a call needs a window bigger than `LLM_NUM_CTX` |
| `LLM_THINK` | `false` | Ollama thinking mode |
| `LLM_KEEP_ALIVE` | `30m` | How long Ollama keeps the weights loaded |
| `LLM_STARTUP_WAIT` | `120` | Seconds a run waits for the Ollama server before aborting |
| `LLM_TIMEOUT` | `900` ollama / `EXTRACT_TIMEOUT` | Per-call timeout (seconds) |
| `LLM_CONCURRENCY` | `1` ollama / `CONCURRENCY` | Parallel model calls |
| `SOURCES` | bundled preset | Comma-separated URLs; blank = preset |
| `KEYWORDS` | none | Relevance filter; blank = keep everything |
| `WINDOW_HOURS` | `24` | How far back to look |
| `PER_FEED_LIMIT` | `10` | Max articles per source |
| `DETAIL_LIMIT` | `20` | Full cards; remainder become a compact list |
| `CONCURRENCY` | `3` | Parallel article fetches; lower if rate-limited |
| `EXTRACT_TIMEOUT` | `90` | Legacy LLM timeout fallback (see `LLM_TIMEOUT`) |
| `MAX_CONTENT_CHARS` | `12000` | Article text sent to the model |
| `LLM_MAX_RETRIES` | `4` | Retries on 429/5xx |
| `LLM_BACKOFF_BASE` | `2` | Backoff seed (seconds) |
| `SAVE_PDF` | `true` | Save a dated PDF of each briefing |
| `PDF_DIR` | this folder | Where those PDFs go (`~` allowed) |
| `ATTACH_PDF` | `false` | Also attach the PDF to the email |
| `CV_PATH` | `cv.pdf` here | PDF used for the weekly skills gap (`~` allowed) |
| `SKILLS_WINDOW_DAYS` | `7` | Days of news history the gap analysis reads |
| `MAX_SKILL_GAPS` | `8` | Entries in "skills to acquire" |
| `HISTORY_KEEP_DAYS` | `60` | Prune daily history older than this |

---

## Verifying a change

```bash
./configure.py --show            # 1. is the value what you expect?
./configure.py --test-llm        # 2. does the model answer?
./configure.py --test-email      # 3. does mail arrive?
./run.sh --dry-run               # 4. full run, no email sent
xdg-open last_briefing.html      #    inspect the result
tail -30 brief.log               #    what happened
./run.sh                         # 5. real run: build + send
```
A dry run processes ~100 articles: minutes on a hosted gateway (and tokens),
tens of minutes on a local model (and nothing). `--test-llm` is the cheap check.

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `SyntaxError: set -euo pipefail` | You ran `python3 run.sh`. It's a bash script — use `./run.sh` or `bash run.sh` |
| `ModuleNotFoundError: feedparser` | You used the system python — use `./run.sh` or `./venv/bin/python brief.py` |
| `HTTP 401` on `--test-llm` | Bad `LLM_API_KEY` (gateway backends) |
| `HTTP 404` on `--test-llm` | `LLM_BASE_URL` missing `/v1`, or wrong `LLM_MODEL` |
| `HTTP 429` | Rate limited — lower `LLM_CONCURRENCY`, raise `LLM_MAX_RETRIES` |
| `no answer from http://localhost:11434` | Ollama isn't running: `systemctl start ollama` (or `ollama serve`) |
| Run aborts with `ollama: …` and exit 3 | Preflight failed — server down or model not pulled; nothing was emailed |
| Cron runs right after a reboot | Raise `LLM_STARTUP_WAIT`, or `systemctl enable ollama` |
| `model 'x' is not pulled` | `ollama pull x` — `--test-llm` lists what's installed |
| Local run times out | Raise `LLM_TIMEOUT`; first call also pays the model-load time |
| Local summaries look vague/generic | `LLM_NUM_CTX` too small for `MAX_CONTENT_CHARS` — the article got truncated |
| Ollama reloads the model constantly | Raise `LLM_KEEP_ALIVE` (`30m`, or `-1` for never) |
| Run is very slow | Expected locally — smaller model, or lower `PER_FEED_LIMIT` / `MAX_CONTENT_CHARS` |
| `temperature is deprecated` | Expected for Opus 4.7+; `brief.py` already omits it |
| SMTP auth rejected | Gmail wants an App Password, not the account password |
| No email but log looks fine | Check `MAIL_TO`; look in spam |
| Cron didn't run | `crontab -l`; check `brief.log`; confirm `run.sh` is executable |
| Few articles, many errors | Usually rate limiting — see `429` above |
| Broke something | `cp .env.bak .env` restores the previous config |
| No PDF appeared | Check `brief.log`; PDF errors are logged but never block the email |
| Skills section missing | Only the `--weekly` run adds it; force one with `./skills.py gaps` |
| "no news history yet" | History builds up per run — do a `./run.sh --dry-run` first |
| CV extracts nothing | It's a scanned image, not a text PDF — export a text version |

Logs: `brief.log` (appended every run). Last output: `last_briefing.html`.

---

## Moving to another machine

```bash
git clone https://github.com/<you>/ai-news-briefing.git
cd ai-news-briefing
python3 -m venv venv && ./venv/bin/pip install -r requirements.txt
scp you@oldbox:~/ai-news-briefing/.env .   # or: ./configure.py to enter fresh
chmod 600 .env
sudo timedatectl set-timezone <Area/City>  # cron uses local time
./configure.py --schedule 10:00
./configure.py --test-llm && ./configure.py --test-email
```
Point it at a model the new box can actually reach: `ollama pull <model>` there,
or `--set LLM_BASE_URL=http://gpu-box:11434` to borrow another machine's Ollama,
or `LLM_PROVIDER=openai` with a gateway if it can't serve a model at all (a
Raspberry Pi, for instance).

Never copy `venv/` between machines — rebuild it so you get the right
architecture wheels. On a very small box you can drop `trafilatura` from
`requirements.txt`; extraction falls back to BeautifulSoup automatically.
