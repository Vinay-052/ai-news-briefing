# Configuring Dispatch

Start the dashboard with `./run.sh`, then open <http://127.0.0.1:8765>.

- **Settings** controls the default AI provider (with **Save & test**), extra provider profiles you can assign per event, SMTP delivery, PDFs, the CV path, and pipeline tuning.
- **Events** controls sources, filters, schedules, time zones, and email delivery. Click **Edit sources** on any event to paste your own feed or publisher URLs.
- **Latest briefing** and **Explore** are the readers. **History** shows completed and failed runs and their delivery status.
- The sidebar's theme switch picks light, dark, or your system setting.

Stored secrets are masked in Settings. Leave a secret field blank to keep its current value, use **Clear saved value** to remove it, or enter a replacement. Enter the appropriate secret when changing providers or SMTP connections.

See the [README](README.md) for setup, headless execution, and migration from earlier releases.
