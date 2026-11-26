"use strict";

const $ = (selector) => document.querySelector(selector);
const dayNames = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const localZone = Intl.DateTimeFormat().resolvedOptions().timeZone;
const dateFormat = new Intl.DateTimeFormat(undefined, {dateStyle: "medium", timeStyle: "short"});
const eventForm = $("#event-form");
const eventDialog = $("#event-dialog");
const settingsForm = $("#settings-form");
let dashboard = {events: [], runs: []};
let presets;
let editing = null;
let settings;
let toastTimer;
let fetching = false;
let lastDashboard = "";

function element(tag, className, content) {
  const item = document.createElement(tag);
  if (className) item.className = className;
  if (content !== undefined) item.textContent = content;
  return item;
}

async function api(path, payload) {
  const options = payload === undefined ? {} : {
    method: "POST",
    headers: {"Content-Type": "application/json", "X-Briefing-Request": "dashboard"},
    body: JSON.stringify(payload),
  };
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Request failed.");
  return data;
}

function notice(text) {
  const toast = $("#toast");
  toast.textContent = text;
  toast.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { toast.hidden = true; }, 5500);
}

function button(label, style, action) {
  const item = element("button", "button " + style, label);
  item.type = "button";
  item.addEventListener("click", action);
  return item;
}

async function refresh() {
  if (fetching) return;
  fetching = true;
  try {
    const data = await api("/api/dashboard");
    const current = JSON.stringify(data);
    if (current !== lastDashboard) {
      dashboard = data;
      lastDashboard = current;
      renderEvents();
      renderRuns();
      renderReportTitle();
    }
  } catch (error) {
    if (!lastDashboard) {
      $("#event-list").replaceChildren(element("p", "empty", error.message));
      $("#recent").replaceChildren(element("p", "empty", "Activity is unavailable."));
    }
  } finally {
    fetching = false;
  }
}

function renderEvents() {
  $("#event-count").textContent = dashboard.events.length + (dashboard.events.length === 1 ? " event" : " events");
  const container = $("#event-list");
  const focused = container.contains(document.activeElement) ? document.activeElement.dataset.focus : null;
  const cards = dashboard.events.map(event => {
    const card = element("article", "event-card");
    const copy = element("div", "event-copy");
    const title = element("div", "event-label");
    const scheduled = event.enabled ? "Scheduled" : "Manual";
    title.append(element("h3", "", event.name), element("span", "pill " + scheduled.toLowerCase(), scheduled));
    const days = event.days.length === 7 ? "Daily" : event.days.map(day => dayNames[day]).join(", ");
    const schedule = event.enabled ? [days, event.time, event.timezone].join(" · ") : "Run on demand";
    copy.append(title, element("p", "meta", schedule),
      element("p", "meta", event.email ? "Web and email" : "Web archive"));
    const actions = element("div", "event-actions");
    const edit = button("Edit", "secondary", () => openEditor(event));
    const run = button("Run now", "primary", () => runEvent(event, run));
    edit.setAttribute("aria-label", "Edit " + event.name);
    run.setAttribute("aria-label", "Run " + event.name + " now");
    edit.dataset.focus = "edit-" + event.id;
    run.dataset.focus = "run-" + event.id;
    run.disabled = dashboard.runs.some(item => item.event_id === event.id && ["queued", "running"].includes(item.status));
    actions.append(edit, run);
    card.append(copy, actions);
    return card;
  });
  container.replaceChildren(...(cards.length ? cards : [element("p", "panel empty", "Create an event to get started.")]));
  if (focused) container.querySelector('[data-focus="' + focused + '"]')?.focus({preventScroll: true});
}

function runRow(run) {
  const row = element("article", "activity-row");
  const copy = element("div");
  const title = element(run.readable ? "a" : "strong", "", run.name);
  if (run.readable) title.href = "#report/" + run.id;
  const details = [dateFormat.format(new Date(run.created * 1000))];
  if (run.article_count !== null) details.push(run.article_count + (run.article_count === 1 ? " article" : " articles"));
  if (run.issues) details.push(run.issues + (run.issues === 1 ? " issue" : " issues"));
  if (run.delivered) details.push("Emailed");
  copy.append(title, element("p", "meta", details.join(" · ")));
  if (run.error) copy.append(element("p", "meta", run.error));
  const status = run.status === "complete" ? "Ready" : run.status[0].toUpperCase() + run.status.slice(1);
  row.append(copy, element("span", "pill " + run.status, status));
  return row;
}

function renderRuns() {
  const filter = $("#archive-filter");
  const selected = filter.value;
  const names = new Map(dashboard.events.map(event => [event.id, event.name]));
  dashboard.runs.forEach(run => { if (!names.has(run.event_id)) names.set(run.event_id, run.name); });
  const choices = [new Option("All events", "")];
  names.forEach((name, id) => choices.push(new Option(name, id)));
  filter.replaceChildren(...choices);
  if (names.has(Number(selected))) filter.value = selected;
  const recent = dashboard.runs.slice(0, 5).map(runRow);
  $("#recent").replaceChildren(...(recent.length ? recent : [element("p", "empty", "Run an event to see its progress here.")]));
  const archived = dashboard.runs.filter(run => !filter.value || run.event_id === Number(filter.value)).map(runRow);
  $("#archive-list").replaceChildren(...(archived.length ? archived : [element("p", "empty", "No runs to show.")]));
}

async function runEvent(event, trigger) {
  trigger.disabled = true;
  try {
    await api("/api/events/" + event.id + "/run", {weekly: false});
    notice(event.name + " queued.");
  } catch (error) {
    notice(error.message);
    trigger.disabled = false;
  }
  await refresh();
}

function updateWeekly() {
  const allowed = eventForm.elements.topic.value.trim().toLowerCase() === "ai";
  $("#weekly-label").hidden = !allowed;
  if (!allowed) eventForm.elements.weekly.checked = false;
}

function fillEditor(data) {
  for (const key of ["name", "topic", "sources", "keywords", "window", "time", "timezone"]) {
    eventForm.elements[key].value = data[key];
  }
  for (const key of ["enabled", "email", "weekly"]) eventForm.elements[key].checked = data[key];
  eventForm.querySelectorAll("[name=days]").forEach(input => { input.checked = data.days.includes(Number(input.value)); });
  updateWeekly();
}

function openEditor(event) {
  editing = event?.id ?? null;
  eventForm.reset();
  $("#event-error").textContent = "";
  $("#dialog-title").textContent = event ? "Edit event" : "New event";
  $("#preset-label").hidden = Boolean(event);
  $("#delete-event").hidden = !event;
  fillEditor(event || {name: "", topic: "", sources: "", keywords: "", window: 24,
    time: "08:00", timezone: localZone || "UTC", days: [0, 1, 2, 3, 4, 5, 6],
    enabled: false, email: false, weekly: false});
  eventDialog.showModal();
  if (event) eventForm.elements.name.focus();
}

dayNames.forEach((day, index) => {
  const label = element("label", "", day);
  const input = element("input");
  input.name = "days";
  input.type = "checkbox";
  input.value = index;
  input.setAttribute("aria-label", day);
  label.append(input);
  $("#weekdays").append(label);
});
$("#new-event").addEventListener("click", () => openEditor());
eventForm.elements.topic.addEventListener("input", updateWeekly);
eventDialog.querySelectorAll(".close").forEach(item => item.addEventListener("click", () => eventDialog.close()));
$("#preset").addEventListener("change", async ({target}) => {
  const value = target.value;
  if (!value) return;
  try {
    presets ||= await api("/api/presets");
    if (target.value === value && eventDialog.open && editing === null) {
      fillEditor({...presets[value], timezone: localZone || presets[value].timezone});
    }
  } catch (error) {
    $("#event-error").textContent = error.message;
  }
});
eventForm.addEventListener("submit", async event => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(eventForm));
  data.window = Number(data.window);
  data.days = new FormData(eventForm).getAll("days").map(Number);
  for (const key of ["enabled", "email", "weekly"]) data[key] = eventForm.elements[key].checked;
  delete data.preset;
  const submit = event.submitter || eventForm.querySelector("[type=submit]");
  submit.disabled = true;
  try {
    await api(editing === null ? "/api/events" : "/api/events/" + editing, data);
    eventDialog.close();
    notice("Event saved.");
    await refresh();
  } catch (error) {
    $("#event-error").textContent = error.message;
  } finally {
    submit.disabled = false;
  }
});
const deleteDialog = $("#delete-dialog");
$("#delete-event").addEventListener("click", () => {
  deleteDialog.returnValue = "";
  deleteDialog.showModal();
});
deleteDialog.addEventListener("close", async () => {
  if (deleteDialog.returnValue !== "delete") return;
  try {
    await api("/api/events/" + editing + "/delete", {});
    eventDialog.close();
    notice("Event deleted.");
    await refresh();
  } catch (error) {
    $("#event-error").textContent = error.message;
  }
});
$("#archive-filter").addEventListener("change", renderRuns);

const providerOptions = {
  auto: "Detect from endpoint", ollama: "Ollama · local or cloud", chatgpt: "OpenAI / ChatGPT API",
  opencode: "OpenCode Console", openai: "OpenAI-compatible gateway",
};
const providerDefaults = {
  ollama: ["http://localhost:11434", "gemma4:26b", "Use your local Ollama server, or enter https://ollama.com and a cloud API key."],
  chatgpt: ["https://api.openai.com/v1", "gpt-4o-mini", "Enter an OpenAI API key and a model available to your API account."],
  opencode: ["https://opencode.ai/inference/openai/v1", "glm-5.3-flash", "Enter an OpenCode Console API key and a text model available for direct API use."],
  openai: ["", "", "Enter the gateway’s API base URL and model ID. Include /v1 if required by the gateway."],
  auto: ["", "", "Detect Ollama from the endpoint and use the Chat Completions API for other endpoints."],
};
const fieldGroups = {
  "#provider-fields": [
    ["LLM_PROVIDER", "Provider", providerOptions], ["LLM_MODEL", "Model ID"],
    ["LLM_BASE_URL", "API base URL"], ["LLM_API_KEY", "API key", "secret"],
    ["REQUIRE_API_KEY", "Require a key for compatible gateways"],
  ],
  "#email-fields": [
    ["SMTP_HOST", "SMTP host"], ["SMTP_PORT", "SMTP port"], ["SMTP_USER", "SMTP username"],
    ["SMTP_PASS", "SMTP password", "secret"], ["SMTP_SECURITY", "Transport security",
      {ssl: "TLS (implicit)", starttls: "STARTTLS", plain: "Plain"}],
    ["MAIL_FROM", "Sender address"], ["MAIL_TO", "Recipient addresses",
      "text", "Separate multiple addresses with commas. Re-enter the SMTP password if the connection changes."],
  ],
  "#report-fields": [
    ["SAVE_PDF", "Save a PDF with each briefing"], ["ATTACH_PDF", "Attach the PDF to email"],
    ["PDF_DIR", "PDF folder", "text", "Leave blank to use the project folder."],
    ["CV_PATH", "CV PDF path", "text", "Leave blank to use cv.pdf in the project folder."],
    ["SKILLS_WINDOW_DAYS", "Skills lookback (days)"], ["MAX_SKILL_GAPS", "Maximum skills to suggest"],
    ["HISTORY_KEEP_DAYS", "AI news history retention (days)"],
  ],
  "#advanced-fields": [
    ["PER_FEED_LIMIT", "Articles per feed"], ["DETAIL_LIMIT", "Full cards per report"],
    ["CONCURRENCY", "Parallel article requests"], ["EXTRACT_TIMEOUT", "Gateway fallback timeout (seconds)"],
    ["MAX_CONTENT_CHARS", "Maximum article characters"], ["LLM_TIMEOUT", "Model timeout (seconds)", "number", "Use 0 for the provider default."],
    ["LLM_CONCURRENCY", "Parallel model requests", "number", "Use 0 for the provider default."],
    ["LLM_MAX_RETRIES", "Model retries"], ["LLM_BACKOFF_BASE", "Retry delay (seconds)", "decimal"],
    ["LLM_NUM_CTX", "Ollama context size"], ["LLM_MAX_NUM_CTX", "Ollama maximum context"],
    ["LLM_KEEP_ALIVE", "Ollama keep-alive"], ["LLM_STARTUP_WAIT", "Ollama startup wait (seconds)"],
    ["LLM_THINK", "Enable local Ollama thinking"],
  ],
};

function renderSettings() {
  for (const [selector, entries] of Object.entries(fieldGroups)) {
    const fields = entries.map(([key, title, kind, hint]) => {
      const value = settings[key];
      const label = element("label", "", title);
      const input = element(typeof kind === "object" ? "select" : "input");
      input.name = key;
      if (typeof kind === "object") {
        Object.entries(kind).forEach(([id, name]) => input.append(new Option(name, id)));
        input.value = value;
      } else if (kind === "secret") {
        input.type = "password";
        input.autocomplete = "new-password";
        input.placeholder = value ? "Saved · leave blank to keep" : "Enter a new secret";
        const clear = button("Clear saved value", "secondary", () => {
          input.dataset.clear = "true";
          input.value = "";
          input.placeholder = "Will clear on save";
        });
        clear.hidden = !value;
        input.addEventListener("input", () => { delete input.dataset.clear; });
        label.append(input);
        const group = element("div", "secret-field");
        group.append(label, clear);
        return group;
      } else if (typeof value === "boolean") {
        input.type = "checkbox";
        input.checked = value;
        label.className = "check";
        label.prepend(input);
        return label;
      } else {
        input.type = typeof value === "number" ? "number" : key === "LLM_BASE_URL" ? "url" : "text";
        input.step = kind === "decimal" ? "any" : "1";
        input.value = value;
        if (typeof value === "number" || key === "LLM_MODEL" || key === "LLM_BASE_URL") input.required = true;
      }
      label.append(input);
      if (hint) label.append(element("span", "hint", hint));
      return label;
    });
    $(selector).replaceChildren(...fields);
  }
  const provider = settingsForm.elements.LLM_PROVIDER;
  $("#provider-help").textContent = providerDefaults[provider.value][2];
  provider.addEventListener("change", () => {
    const [url, model, help] = providerDefaults[provider.value];
    settingsForm.elements.LLM_BASE_URL.value = url;
    settingsForm.elements.LLM_MODEL.value = model;
    $("#provider-help").textContent = help + " Enter the key for the new endpoint if it uses one.";
  });
}

async function openSettings() {
  const submit = settingsForm.querySelector("[type=submit]");
  submit.disabled = true;
  try {
    settings = await api("/api/settings");
    renderSettings();
    $("#settings-error").textContent = "";
    submit.disabled = false;
  } catch (error) {
    $("#settings-error").textContent = error.message;
  }
}

settingsForm.addEventListener("submit", async event => {
  event.preventDefault();
  const data = {};
  for (const input of settingsForm.querySelectorAll("[name]")) {
    if (input.type === "checkbox") data[input.name] = input.checked;
    else if (input.type === "number") data[input.name] = Number(input.value);
    else data[input.name] = input.dataset.clear ? null : input.value;
  }
  const submit = event.submitter || settingsForm.querySelector("[type=submit]");
  submit.disabled = true;
  try {
    settings = await api("/api/settings", data);
    renderSettings();
    $("#settings-error").textContent = "";
    notice("Settings saved.");
  } catch (error) {
    $("#settings-error").textContent = error.message;
  } finally {
    submit.disabled = false;
  }
});

function renderReportTitle() {
  const id = /^#report\/(\d+)$/.exec(location.hash)?.[1];
  if (!id) return;
  $("#report-title").textContent = dashboard.runs.find(run => run.id === Number(id))?.name || "Briefing";
}

function route() {
  const report = /^#report\/(\d+)$/.exec(location.hash);
  const view = report ? "report" : ["#archive", "#settings"].includes(location.hash) ? location.hash.slice(1) : "events";
  document.querySelectorAll("main > section").forEach(section => { section.hidden = section.id !== view; });
  document.querySelectorAll("nav a").forEach(link => {
    if (link.hash === "#" + (view === "report" ? "archive" : view)) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  if (view === "settings" && !settings) openSettings();
  if (report) {
    const url = "/reports/" + report[1];
    $("#open-report").href = url;
    $("#report-frame").src = url;
    renderReportTitle();
  } else {
    $("#report-frame").removeAttribute("src");
  }
  window.scrollTo(0, 0);
}

window.addEventListener("hashchange", route);
route();
void refresh();
setInterval(refresh, 4000);
