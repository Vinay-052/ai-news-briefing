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

### Rotate the LLM API key
```bash
./configure.py --set LLM_API_KEY=sk-newkey... --test-llm
```
Or `./configure.py --llm` to be prompted (the key is hidden as you type).

### Switch model, or move to a different provider/gateway
```bash
# same gateway, different model
./configure.py --set LLM_MODEL=claude-opus-5 --test-llm

# different provider entirely
./configure.py --set LLM_BASE_URL=https://api.openai.com/v1 \
               --set LLM_API_KEY=sk-... \
               --set LLM_MODEL=gpt-4o --test-llm
```
Any **OpenAI-compatible** `/chat/completions` endpoint works — hosted gateways,
OpenAI, or a local Ollama (`http://localhost:11434/v1`, any key value).
`LLM_BASE_URL` should end in `/v1`; the script appends `/chat/completions`.

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
Cron uses **local time**, and this box is `Asia/Kolkata`, so `10:00` means
10:00 IST. On a new machine set the zone first:
`sudo timedatectl set-timezone Asia/Kolkata`.

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
| `LLM_BASE_URL` | — | OpenAI-compatible base, ending `/v1` |
| `LLM_API_KEY` | — | Sent as `Authorization: Bearer <key>` |
| `LLM_MODEL` | — | Model id |
| `SOURCES` | bundled preset | Comma-separated URLs; blank = preset |
| `KEYWORDS` | none | Relevance filter; blank = keep everything |
| `WINDOW_HOURS` | `24` | How far back to look |
| `PER_FEED_LIMIT` | `10` | Max articles per source |
| `DETAIL_LIMIT` | `20` | Full cards; remainder become a compact list |
| `CONCURRENCY` | `3` | Parallel summaries; lower if rate-limited |
| `EXTRACT_TIMEOUT` | `90` | Per-article LLM timeout (seconds) |
| `MAX_CONTENT_CHARS` | `12000` | Article text sent to the model |
| `LLM_MAX_RETRIES` | `4` | Retries on 429/5xx |
| `LLM_BACKOFF_BASE` | `2` | Backoff seed (seconds) |

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
A dry run takes a few minutes (~100 articles) and costs tokens; `--test-llm` is
the cheap check.

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `HTTP 401` on `--test-llm` | Bad `LLM_API_KEY` |
| `HTTP 404` on `--test-llm` | `LLM_BASE_URL` missing `/v1`, or wrong `LLM_MODEL` |
| `HTTP 429` | Rate limited — lower `CONCURRENCY`, raise `LLM_MAX_RETRIES` |
| `temperature is deprecated` | Expected for Opus 4.7+; `brief.py` already omits it |
| SMTP auth rejected | Gmail wants an App Password, not the account password |
| No email but log looks fine | Check `MAIL_TO`; look in spam |
| Cron didn't run | `crontab -l`; check `brief.log`; confirm `run.sh` is executable |
| Few articles, many errors | Usually rate limiting — see `429` above |
| Broke something | `cp .env.bak .env` restores the previous config |

Logs: `brief.log` (appended every run). Last output: `last_briefing.html`.

---

## Moving to another machine (e.g. Raspberry Pi)

```bash
git clone http://<gitea-host>:3000/claude/ai-news-briefing.git
cd ai-news-briefing
python3 -m venv venv && ./venv/bin/pip install -r requirements.txt
scp you@oldbox:~/ai-news-briefing/.env .   # or: ./configure.py to enter fresh
chmod 600 .env
sudo timedatectl set-timezone Asia/Kolkata
./configure.py --schedule 10:00
./configure.py --test-llm && ./configure.py --test-email
```
Never copy `venv/` between machines — rebuild it so you get the right
architecture wheels. On a very small box you can drop `trafilatura` from
`requirements.txt`; extraction falls back to BeautifulSoup automatically.
