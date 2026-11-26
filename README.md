# Dispatch · News Briefing

Dispatch turns RSS feeds and publisher pages into scheduled briefings with linked citations. Read each edition in the web reader (filter by category, signal and audience, or search across every past edition), send it by email, or run the same pipeline unattended on an always-on computer.

## Start the dashboard

Requires Python 3.9+ on macOS or Linux.

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
./run.sh
```

Run it from a terminal and open <http://127.0.0.1:8765>. All app settings are in the dashboard. Use `./run.sh serve` to start the dashboard from a service manager such as launchd or systemd. The server listens on loopback. For phone access, use an authenticated HTTPS reverse proxy on your private network that forwards to `127.0.0.1:8765` with `Host: 127.0.0.1:8765`. The dashboard assumes any client reaching it through the proxy has already authenticated.

1. Open **Settings**, choose the default provider, paste its API key, pick a model from **Load models** (or type an ID), then click **Save & test**. Hosted providers can't be saved without a key. Add SMTP details if you want email delivery. Under **More providers** you can save extra models, such as ChatGPT, Claude or OpenCode, and assign one per event.
2. Open **Events**. Edit the existing AI event or create a new event from AI News, Politics, Latest Trends, or Custom.
3. Paste your own feed or publisher URLs into **News source URLs**, one per line. Use **Edit sources** on any event to add or replace URLs later. Set the lookback, days, time, time zone, and delivery preference, then enable the schedule when ready.
4. Use **Run now** (or **Refresh now** in the reader) to generate an edition immediately. The dashboard tells you when it's ready.
5. Read it under **Latest briefing**. Each story shows what happened, why it matters, a takeaway, a blunt read, scores, and numbered citations to the original reporting and related coverage. Switch between **Full briefing**, **Quick scan** and **Headlines**, or filter by category, signal, audience and keyword. **Explore** searches every edition at once. **History** lists every run, **View email layout** shows the exact email, and **Email this edition** re-sends any past edition.

Every preset, including AI news, fills in editable starter URLs. The event editor shows the full list: the briefing reads exactly those URLs, adding a URL keeps the others, and × removes one. On first start after upgrading, an AI event with an empty source list is filled in with the 25 starter URLs it was already using.

## AI providers

| Provider | Endpoint and credentials |
| --- | --- |
| Ollama local | Use `http://localhost:11434` and a model already installed in Ollama. |
| Ollama Cloud | Use `https://ollama.com` with an Ollama API key and cloud model. |
| OpenAI / ChatGPT API | Uses the OpenAI Responses API with an OpenAI API key and an API-accessible model. |
| Anthropic / Claude API | Uses the Anthropic Messages API (`https://api.anthropic.com/v1`) with a Claude API key. |
| OpenCode Console | Uses the Console's OpenAI-compatible inference endpoint (`https://opencode.ai/inference/openai/v1`) with a Console API key and a model available for direct API use. |
| OpenAI-compatible gateway | Enter the service's API base URL, model ID, and key. For a trusted keyless gateway, clear **Require a key for compatible gateways**. |

The default provider applies to every event. Add more under **Settings → More providers** and choose one per event in the event editor. **Save & test** sends a one-word prompt so you can catch a bad key or model before a scheduled run. ChatGPT Plus and other consumer subscriptions don't include API access, so each provider needs an API key from its developer console.

For available models and API details, see the [OpenAI Responses API](https://developers.openai.com/api/reference/resources/responses/methods/create) and [OpenCode Console model endpoints](https://opencode.ai/docs/console/models/).

## Unattended runs

The dashboard's server runs the scheduler even when the browser is closed. You can also run a worker with no HTTP listener, or trigger one scheduler pass periodically from an existing system scheduler.

```bash
./run.sh worker
./run.sh tick
```

Each enabled event can run once per scheduled local date. The worker catches up a due slot within 24 hours of its scheduled time. Enabling an event or changing its days, time, or time zone starts the new schedule from the time of that change. The workers share a lock so dashboard, cron, and CLI runs use one pipeline at a time. If the worker exits mid-run, the archive marks the interrupted run as failed on restart. You can rerun it from the event.

Headless commands use dashboard settings. Existing cron entries keep working unchanged: with no terminal attached, a bare `./run.sh` runs the headless briefing as it always did. From an interactive terminal it starts the dashboard. Calls with `headless`, `--dry-run`, `--weekly`, or `--event` always run headless.

```bash
./run.sh headless                 # run the original AI event using its delivery preference
./run.sh --dry-run                # archive and write last_briefing.html, skip email
./run.sh --weekly                 # include the CV skills gap
./run.sh --event 2                # run an event by ID (see dashboard API at /api/dashboard)
```

Use either the old direct cron entries or the dashboard schedule for the same event to avoid duplicate editions. Existing `.env` and process environment settings serve as defaults. The initial AI event takes its sources, keywords, lookback, and SMTP availability from those defaults, and starts with its dashboard schedule disabled. Set the next schedule in the dashboard before retiring existing cron entries.

## PDF and weekly skills

Enable PDF archiving and optional email attachments in **Settings**. For AI events, enable the Sunday skills gap and set the path to your CV PDF, or use `cv.pdf` in the project folder. The existing skills commands remain available for viewing and tracking the report.

```bash
./venv/bin/python skills.py
./venv/bin/python skills.py gaps
./venv/bin/python skills.py learned "vLLM"
```

Settings, credentials, schedules, and archived HTML are stored under the private, gitignored `.briefing/` directory. Back up this directory to move the app to another machine. Keep your CV, `.env`, briefing PDFs, and AI skills history private as well.

## Tests

```bash
./venv/bin/python -m unittest discover -s tests -v
```

The tests cover scheduling, provider requests (Ollama, ChatGPT, Claude, OpenCode, compatible gateways), provider profiles, the reader and Explore APIs, email delivery and resend, and the HTTP security checks.

MIT license. See [LICENSE](LICENSE).
