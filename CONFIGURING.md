# Configuring Dispatch

Start the dashboard with `./run.sh`, then open <http://127.0.0.1:8765>.

- **Settings** controls AI providers, SMTP delivery, PDFs, the CV path, and pipeline tuning.
- **Events** controls sources, filters, schedules, time zones, and email delivery. Click **Edit sources** on any event to paste your own feed or publisher URLs.
- **Archive** shows completed and failed runs, delivery status, and links to completed briefings.

Stored secrets are masked in Settings. Leave a secret field blank to keep its current value, use **Clear saved value** to remove it, or enter a replacement. Enter the appropriate secret when changing providers or SMTP connections.

See the [README](README.md) for setup, headless execution, and migration from earlier releases.
