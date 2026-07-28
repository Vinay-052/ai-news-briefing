# AI News Briefing (standalone)

A single daily job: fetch AI-news feeds, summarize + score each article with an
LLM, and email a scannable HTML briefing. No web app, no database — just a
script, a `.env`, and a cron line. Runs happily on a Raspberry Pi 4.

## Files
- `brief.py` — the whole pipeline (fetch → extract → LLM classify/score → dedup → rank → HTML → email).
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
cp .env.example .env         # then edit .env with your LLM + SMTP creds
chmod 600 .env

# test without sending — writes last_briefing.html
./venv/bin/python brief.py --dry-run
xdg-open last_briefing.html   # or just open it in a browser

# send for real
./venv/bin/python brief.py
```

For a lean Pi build you can skip `trafilatura` (drop it from requirements);
extraction falls back to BeautifulSoup automatically.

## Schedule (cron, 10:00 local time)
Set the box timezone first so `10:00` means your local 10am:
```bash
sudo timedatectl set-timezone Asia/Kolkata
```
Then add a user crontab entry (`crontab -e`):
```
0 10 * * * /home/vinay/ai-news-briefing/run.sh
```
Logs append to `brief.log`. Run `./run.sh --dry-run` to test the cron path.

## Redeploying to a Raspberry Pi
1. Copy this folder to the Pi (`scp -r ai-news-briefing pi@host:~/`). **Do not copy `venv/`** — rebuild it on the Pi.
2. `python3 -m venv venv && ./venv/bin/pip install -r requirements.txt`
3. Copy your `.env` (it's portable; keep it `chmod 600`).
4. Set the timezone and add the cron line as above.
That's it — no services, no ports, no database.
