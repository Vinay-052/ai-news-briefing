# AI News Briefing (standalone)

A single daily job: fetch AI-news feeds, summarize + score each article with an
LLM, and email a scannable HTML briefing. No web app, no database — just a
script, a `.env`, and a cron line.

Each run also saves a dated PDF of the briefing, and once a week it compares the
news against your CV and tells you which skills to pick up.

**It runs on a local model by default.** Point it at [Ollama](https://ollama.com)
and the whole thing costs nothing per run and keeps your reading list on your own
machine. No GPU? [Ollama Cloud](https://docs.ollama.com/cloud) uses the identical
API, so a 16 GB N100 mini PC can run the whole job. Any OpenAI-compatible gateway
works too.

## LLM backend
Two providers, chosen with `LLM_PROVIDER`:

| | `ollama` local (default) | `ollama` cloud | `openai` |
|---|---|---|---|
| Endpoint | `POST {base}/api/chat` | same, on `ollama.com` | `POST {base}/chat/completions` |
| Base URL | `http://localhost:11434` | `https://ollama.com` | e.g. `https://api.openai.com/v1` |
| API key | not used | required | required |
| Hardware | your GPU/RAM | none | none |
| Cost | electricity | subscription | per token |

`LLM_PROVIDER=auto` sniffs the base URL and picks `ollama` for an Ollama host.

### Local Ollama
```bash
ollama pull gemma4:26b                      # ~17 GB
./configure.py --use-ollama gemma4:26b      # writes provider/URL/model, clears the API key
./configure.py --test-llm                   # confirm it answers
```

### Ollama Cloud
The same native API on somebody else's GPU, so a small always-on box (an N100
mini PC, a Pi) can run the whole briefing:

```bash
./configure.py --set LLM_API_KEY=<your-key> --use-ollama-cloud gpt-oss:120b
./configure.py --test-llm
```
Cloud runs skip the local-only bits automatically: no `keep_alive` (there are no
weights to hold), no waiting for a service to boot, and `LLM_CONCURRENCY`
defaults to `CONCURRENCY` instead of 1, since a hosted service serves parallel
requests. Rate limits surface as HTTP 429, which the existing retry/backoff
already handles.

Why the native `/api/chat` and not Ollama's `/v1` shim: only the native API
accepts `num_ctx` (the shim's default window silently truncates a 12 000-char
article) and `think` (thinking mode would spend the output budget on reasoning
the briefing throws away).

Tuning that matters locally — all optional, defaults in brackets:
- `LLM_NUM_CTX` [8192] — must cover `MAX_CONTENT_CHARS`/4 plus the prompt.
- `LLM_CONCURRENCY` [1 for ollama] — one GPU serves one request at a time;
  article *fetching* stays parallel via `CONCURRENCY`.
- `LLM_TIMEOUT` [900s for ollama] — local generation is minutes, not seconds.
- `LLM_KEEP_ALIVE` [30m] — keeps the weights resident, so a 90-article run
  doesn't reload them.
- `LLM_THINK` [false] — leave off for JSON work.

Hardware: a ~26B model at Q4 wants ~20 GB of (V)RAM and takes roughly 30-60 s
per article. A smaller model (`ollama pull gemma4:6b`, `qwen3:8b`) cuts that a
lot; drop `PER_FEED_LIMIT`/`MAX_CONTENT_CHARS` to cut it further. On a machine
too small to serve a model at all — a Raspberry Pi, say — use
`LLM_PROVIDER=openai` and point at a gateway, or at an Ollama server on
another box (`LLM_BASE_URL=http://that-box:11434`).

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
./configure.py --set PDF_DIR=~/briefings
./configure.py --set ATTACH_PDF=true      # also attach it to the email
```

## Weekly skills gap
Drop your CV in this folder as `cv.pdf` (or point `CV_PATH` at it:
`./configure.py --set CV_PATH=~/docs/my_cv.pdf`). It stays out of git.

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

## Setup
Needs Python 3.9+ and, for the default local backend, Ollama running.
```bash
git clone https://github.com/<you>/ai-news-briefing.git
cd ai-news-briefing
python3 -m venv venv
./venv/bin/pip install -r requirements.txt

ollama pull gemma4:26b                    # or any model you can run
./configure.py --use-ollama gemma4:26b    # skip if you're using a gateway
./configure.py                            # SMTP settings (writes .env, chmod 600)
./configure.py --test-llm                 # confirm the model answers
./configure.py --test-email               # confirm mail arrives

./run.sh --dry-run           # full run, no email — writes last_briefing.html
xdg-open last_briefing.html
./run.sh                     # build + send for real
```

On a small machine you can skip `trafilatura` (drop it from requirements);
extraction falls back to BeautifulSoup automatically.

## Changing settings later
Never hand-edit `.env` — use the tool (validates, keeps a `.env.bak`):
```bash
./configure.py --show                          # current config, secrets masked
./configure.py --set MAIL_TO=you@example.com   # change the recipient
./configure.py --set LLM_MODEL=gemma4:6b       # switch model
./configure.py --use-ollama                    # move to a local model
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

## Moving it to another machine
1. Clone this repo there (or copy the folder — but **never copy `venv/`**).
2. `python3 -m venv venv && ./venv/bin/pip install -r requirements.txt`
3. Bring your `.env` across (it's portable; keep it `chmod 600`) — or just run
   `./configure.py` and enter the settings fresh.
4. Make sure the model backend is reachable from there: `ollama pull <model>`
   locally, or `./configure.py --set LLM_BASE_URL=http://gpu-box:11434` to use
   an Ollama server elsewhere on your network.
5. `sudo timedatectl set-timezone <Area/City>` then `./configure.py --schedule 10:00`.
6. `./configure.py --test-llm && ./configure.py --test-email`

That's it — no services, no ports, no database.

## License
MIT — see [LICENSE](LICENSE).
