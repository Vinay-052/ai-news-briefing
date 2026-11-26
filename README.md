# Dispatch · News Briefing

Dispatch turns RSS feeds and publisher pages into scheduled briefings with linked citations. Read editions in the web archive, send them by email, or run the same pipeline unattended on an always-on computer.

## Start the dashboard

Requires Python 3.9+ on macOS or Linux.

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
./venv/bin/python webapp.py
```

Open <http://127.0.0.1:8765>. All app settings are in the dashboard. The server listens on loopback. For phone access, use an authenticated HTTPS reverse proxy on your private network that forwards to `127.0.0.1:8765` with `Host: 127.0.0.1:8765`. The dashboard assumes any client reaching it through the proxy has already authenticated.

1. Open **Settings** and enter your provider and model. Add SMTP details if you want email delivery.
2. Open **Events**. Edit the existing AI event or create a new event from AI News, Politics, Latest Trends, or Custom.
3. Set the topic, source URLs, lookback, days, time, time zone, and delivery preference. Enable the schedule when ready.
4. Use **Run now** to generate an edition immediately. Follow its progress in **Recent activity** and open the edition from **Archive**. The email and web editions both link to the original reporting and available related sources.

The politics and trends presets contain editable starter feeds. Add sources that fit your geography and interests. The AI event uses the bundled AI feeds when its source field is blank.

## AI providers

| Provider | Endpoint and credentials |
| --- | --- |
| Ollama local | Use `http://localhost:11434` and a model already installed in Ollama. |
| Ollama Cloud | Use `https://ollama.com` with an Ollama API key and cloud model. |
| OpenAI / ChatGPT API | Uses the OpenAI Responses API with an OpenAI API key and an API-accessible model. |
| OpenCode Console | Uses the Console's OpenAI-compatible inference endpoint with a Console API key and a model available for direct API use. |
| OpenAI-compatible gateway | Enter the service's API base URL, model ID, and key. For a trusted keyless gateway, clear **Require a key for compatible gateways**. |

For available models and API details, see the [OpenAI Responses API](https://developers.openai.com/api/reference/resources/responses/methods/create) and [OpenCode Console model endpoints](https://opencode.ai/docs/console/models/).

## Unattended runs

The dashboard's server runs the scheduler even when the browser is closed. You can also run a worker with no HTTP listener, or trigger one scheduler pass periodically from an existing system scheduler.

```bash
./venv/bin/python webapp.py worker
./venv/bin/python webapp.py tick
```

Each enabled event can run once per scheduled local date. The worker catches up a due slot within 24 hours of its scheduled time. Enabling an event or changing its days, time, or time zone starts the new schedule from the time of that change. The workers share a lock so dashboard, cron, and CLI runs use one pipeline at a time. If the worker exits mid-run, the archive marks the interrupted run as failed on restart. You can rerun it from the event.

Existing headless commands still work and use dashboard settings.

```bash
./run.sh                          # run the original AI event and use its delivery preference
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
node --check web/app.js
```

MIT license. See [LICENSE](LICENSE).
