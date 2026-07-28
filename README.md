# AI News Briefing (standalone)

A single daily job: fetch AI-news feeds, summarize + score each article with an
LLM, and email a scannable HTML briefing. No web app, no database — just a
script, a `.env`, and a cron line. Runs happily on a Raspberry Pi 4.

Each run also saves a dated PDF of the briefing, and once a week it compares the
news against your CV and tells you which skills to pick up.

## Files
- `brief.py` — the whole pipeline (fetch → extract → LLM classify/score → dedup → rank → HTML/PDF → email).
- `configure.py` — change any setting or the schedule; see **[CONFIGURING.md](CONFIGURING.md)**.
- `skills.py` — the skills gap: view it, and mark skills off as you learn them.
- `skills_gap.py` — CV parsing, news history, and the gap analysis.
- `pdf_report.py` — the PDF renderer (`fpdf2`, no system libraries).
- `sources.py` — curated "AI News" preset + feed auto-discovery map.
- `taxonomy.py` — categories/signals/audiences + deterministic scoring.
- `render.py` — the card-based HTML email renderer.
- `config.py` — reads `.env`.
- `requirements.txt` — `feedparser`, `httpx`, `beautifulsoup4`, `fpdf2`, `pypdf` (+ optional `trafilatura`).

Not in git (personal / regenerable): `.env`, your CV PDF, `skills.json`,
`history/`, saved report PDFs, `brief.log`.

## PDF archive
Every run writes `AI_News_Briefing_<YYYY-MM-DD>_<HHMM>.pdf` into this folder —
the same briefing as the email, laid out for print. Turn it off or move it:
```bash
./configure.py --set SAVE_PDF=false
./configure.py --set PDF_DIR=/home/vinay/briefings
./configure.py --set ATTACH_PDF=true      # also attach it to the email
```

## Weekly skills gap
Sunday's run (`run.sh --weekly`) additionally reads the week's news history,
compares it with the skills on your CV, and appends a **"Skills to acquire"**
section — each entry with why it matters now, search keywords to learn it, and
which stories it came from. It lands in both the email and the PDF.

```bash
./skills.py                 # overview: CV skills, learned, current gaps
./skills.py gaps            # re-run the analysis now (uses stored history)
./skills.py gaps --send     # ...and email just the skills report
./skills.py learned "vLLM"  # mark learned -> never suggested again
./skills.py cv              # what it read from your CV
./skills.py refresh-cv      # after you update the CV PDF
```
The CV is parsed once and cached (keyed on the file's hash), so it's only
re-read when the PDF actually changes.

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
./configure.py --schedule 10:00              # daily; Sunday also does the skills gap
./configure.py --schedule 10:00 --weekly-day 6   # move the skills run to Saturday
./configure.py --schedule off                # stop automatic runs
```
This installs two entries — Mon-Sat run the plain briefing, the weekly day runs
it with `--weekly` — so you still get exactly one email per day.
Logs append to `brief.log`. Run `./run.sh --dry-run` to test the cron path.

## Redeploying to a Raspberry Pi
1. Clone this repo on the Pi (or `scp` the folder — but **never copy `venv/`**).
2. `python3 -m venv venv && ./venv/bin/pip install -r requirements.txt`
3. Bring your `.env` across (it's portable; keep it `chmod 600`) — or just run
   `./configure.py` and enter the settings fresh.
4. `sudo timedatectl set-timezone Asia/Kolkata` then `./configure.py --schedule 10:00`.
5. `./configure.py --test-llm && ./configure.py --test-email`

That's it — no services, no ports, no database.
