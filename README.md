# AI News Briefing (standalone)

A single daily job: fetch AI-news feeds, summarize + score each article with an
LLM, and email a scannable HTML briefing. No web app, no database — just a
script, a `.env`, and a cron line. Runs happily on a Raspberry Pi 4.

## Files
- `brief.py` — the whole pipeline (fetch → extract → LLM classify/score → dedup → rank → HTML → email).
- `configure.py` — change any setting or the schedule; see **[CONFIGURING.md](CONFIGURING.md)**.
- `sources.py` — curated "AI News" preset + feed auto-discovery map.
- `taxonomy.py` — categories/signals/audiences + deterministic scoring.
- `render.py` — the card-based HTML email renderer.
- `config.py` — reads `.env`.
- `requirements.txt` — `feedparser`, `httpx`, `beautifulsoup4` (+ optional `trafilatura`).

## Setup (first machine or Raspberry Pi)
```bash
cd ai-news-briefing
python3 -m venv venv
./venv/bin/pip install -r requirements.txt

./configure.py               # enter LLM + SMTP settings (writes .env, chmod 600)
./configure.py --test-llm    # confirm the model answers
./configure.py --test-email  # confirm mail arrives

./run.sh --dry-run           # full run, no email — writes last_briefing.html
xdg-open last_briefing.html
./run.sh                     # build + send for real
```

For a lean Pi build you can skip `trafilatura` (drop it from requirements);
extraction falls back to BeautifulSoup automatically.

## Changing settings later
Never hand-edit `.env` — use the tool (validates, keeps a `.env.bak`):
```bash
./configure.py --show                          # current config, secrets masked
./configure.py --set MAIL_TO=you@example.com   # change the recipient
./configure.py --set LLM_MODEL=claude-opus-5   # switch model
./configure.py --llm                           # rotate key / change endpoint
```
Full cookbook — recipients, API keys, endpoints, sources, schedule,
troubleshooting: **[CONFIGURING.md](CONFIGURING.md)**.

## Schedule (cron, local time)
```bash
sudo timedatectl set-timezone Asia/Kolkata   # so 10:00 means your local 10am
./configure.py --schedule 10:00              # writes the crontab entry
./configure.py --schedule off                # stop automatic runs
```
Logs append to `brief.log`. Run `./run.sh --dry-run` to test the cron path.

## Redeploying to a Raspberry Pi
1. Clone this repo on the Pi (or `scp` the folder — but **never copy `venv/`**).
2. `python3 -m venv venv && ./venv/bin/pip install -r requirements.txt`
3. Bring your `.env` across (it's portable; keep it `chmod 600`) — or just run
   `./configure.py` and enter the settings fresh.
4. `sudo timedatectl set-timezone Asia/Kolkata` then `./configure.py --schedule 10:00`.
5. `./configure.py --test-llm && ./configure.py --test-email`

That's it — no services, no ports, no database.
