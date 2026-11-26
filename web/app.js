"use strict";

/* Dispatch dashboard. Plain DOM, no build step. Text is always set with
   textContent and links only accept http(s), because article data comes from
   third-party feeds and model output. */

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const dayNames = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const localZone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
const dateFormat = new Intl.DateTimeFormat(undefined, {dateStyle: "medium", timeStyle: "short"});
const longDate = new Intl.DateTimeFormat(undefined, {weekday: "long", month: "long", day: "numeric", hour: "numeric", minute: "2-digit"});
const timeOnly = new Intl.DateTimeFormat(undefined, {weekday: "short", hour: "numeric", minute: "2-digit"});
const relative = new Intl.RelativeTimeFormat(undefined, {numeric: "auto"});
const scoreLabels = [["practical", "Practical"], ["technical", "Technical"], ["market", "Market"], ["urgency", "Urgency"], ["hype_risk", "Hype risk"]];
const providerTypes = {
  ollama: ["Ollama · local or cloud", "http://localhost:11434", "gemma4:26b", "Your own Ollama server, or https://ollama.com with an Ollama API key."],
  chatgpt: ["OpenAI / ChatGPT API", "https://api.openai.com/v1", "gpt-5-mini", "Uses the OpenAI Responses API. Needs an OpenAI API key (ChatGPT Plus subscriptions don't include API access)."],
  anthropic: ["Anthropic / Claude API", "https://api.anthropic.com/v1", "claude-haiku-5-5", "Uses the Anthropic Messages API with a Claude API key."],
  opencode: ["OpenCode Console", "https://opencode.ai/inference/openai/v1", "glm-5.3-flash", "OpenCode Console's OpenAI-compatible endpoint. Needs a Console API key; use a model listed for direct API use."],
  openai: ["OpenAI-compatible gateway", "", "", "Any service with a /chat/completions endpoint: OpenRouter, LiteLLM, LM Studio, vLLM, Groq and others."],
};
const defaultProviderTypes = {auto: ["Detect from endpoint", "", "", "Detects Ollama from the endpoint and uses Chat Completions for anything else."], ...providerTypes};

let dashboard = {events: [], runs: [], providers: [], ready: {model: "", email: false}};
let lastDashboard = "";
let settings = null;
let presets = null;
let editingEvent = null;
let editingProvider = null;
let fetching = false;
let currentView = "";
const editions = new Map();       // run id -> structured edition
let exploreCache = {key: "", articles: []};
let selectedEvent = null;         // event id the reader follows when no run is pinned

/* ---------- Small helpers ---------- */
function el(tag, className, content) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (content !== undefined && content !== null) node.textContent = content;
  return node;
}
function icon(path) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  const shape = document.createElementNS("http://www.w3.org/2000/svg", "path");
  shape.setAttribute("d", path);
  svg.append(shape);
  return svg;
}
const icons = {
  clock: "M12 7v5l3 2M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z",
  mail: "M4 6h16v12H4zM4 7l8 6 8-6",
  feed: "M5 19a1 1 0 1 0 0-2 1 1 0 0 0 0 2zM4 11a9 9 0 0 1 9 9M4 4a16 16 0 0 1 16 16",
  chip: "M7 7h10v10H7zM10 3v4M14 3v4M10 17v4M14 17v4M3 10h4M3 14h4M17 10h4M17 14h4",
  play: "M7 5l12 7-12 7z",
  pencil: "M4 20h4L19 9l-4-4L4 16zM13 7l4 4",
};
function safeHref(url) {
  try {
    const parsed = new URL(url);
    return ["http:", "https:"].includes(parsed.protocol) ? parsed.href : null;
  } catch { return null; }
}
function link(url, text, className) {
  const href = safeHref(url);
  if (!href) return el("span", className, text);
  const a = el("a", className, text);
  a.href = href;
  a.target = "_blank";
  a.rel = "noopener noreferrer";
  return a;
}
function ago(seconds) {
  if (!seconds) return "";
  const diff = seconds - Date.now() / 1000;
  const abs = Math.abs(diff);
  for (const [unit, size] of [["day", 86400], ["hour", 3600], ["minute", 60]]) {
    if (abs >= size) return relative.format(Math.round(diff / size), unit);
  }
  return diff > 0 ? "in under a minute" : "just now";
}
function plural(n, word) { return n + " " + word + (n === 1 ? "" : "s"); }
function reveal(node, index) {
  node.classList.add("reveal");
  node.style.setProperty("--i", index);
  return node;
}

async function api(path, payload) {
  const options = payload === undefined ? {} : {
    method: "POST",
    headers: {"Content-Type": "application/json", "X-Briefing-Request": "dashboard"},
    body: JSON.stringify(payload),
  };
  const response = await fetch(path, options);
  let data = {};
  try { data = await response.json(); } catch { /* empty body */ }
  if (!response.ok) throw new Error(data.error || "Request failed (" + response.status + ").");
  return data;
}

function toast(text, kind = "") {
  const node = el("div", "toast " + kind, text);
  $("#toasts").append(node);
  setTimeout(() => {
    node.classList.add("leaving");
    node.addEventListener("animationend", () => node.remove(), {once: true});
  }, kind === "error" ? 7000 : 4200);
}

async function busy(buttonNode, work) {
  buttonNode.disabled = true;
  buttonNode.classList.add("busy");
  try { return await work(); } finally {
    buttonNode.disabled = false;
    buttonNode.classList.remove("busy");
  }
}

/* Dialogs animate out before closing. */
function closeDialog(dialog) {
  if (!dialog.open || dialog.classList.contains("closing")) return;
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) { dialog.close(); return; }
  dialog.classList.add("closing");
  dialog.addEventListener("animationend", () => { dialog.classList.remove("closing"); dialog.close(); }, {once: true});
}
$$("dialog").forEach(dialog => {
  dialog.addEventListener("cancel", event => { event.preventDefault(); closeDialog(dialog); });
  dialog.addEventListener("click", event => { if (event.target === dialog) closeDialog(dialog); });
  $$(".close", dialog).forEach(node => node.addEventListener("click", () => closeDialog(dialog)));
});
function confirmAction(title, text, okLabel = "Delete") {
  const dialog = $("#confirm-dialog");
  $("#confirm-title").textContent = title;
  $("#confirm-text").textContent = text;
  $("#confirm-ok").textContent = okLabel;
  dialog.returnValue = "";
  dialog.showModal();
  return new Promise(resolve => dialog.addEventListener("close", () => resolve(dialog.returnValue === "ok"), {once: true}));
}

/* ---------- Theme ---------- */
function applyTheme(choice) {
  if (choice === "light" || choice === "dark") document.documentElement.dataset.theme = choice;
  else delete document.documentElement.dataset.theme;
  $$("[data-theme-choice]").forEach(b => b.setAttribute("aria-checked", String(b.dataset.themeChoice === choice)));
}
let themeChoice = "system";
try { themeChoice = localStorage.getItem("dispatch-theme") || "system"; } catch { /* storage blocked */ }
applyTheme(themeChoice);
$$("[data-theme-choice]").forEach(b => b.addEventListener("click", () => {
  const choice = b.dataset.themeChoice;
  const swap = () => applyTheme(choice);
  if (document.startViewTransition && !matchMedia("(prefers-reduced-motion: reduce)").matches) document.startViewTransition(swap);
  else swap();
  try { localStorage.setItem("dispatch-theme", choice); } catch { /* storage blocked */ }
}));

/* ---------- Mobile drawer ---------- */
function setDrawer(open) {
  $("#sidebar").classList.toggle("open", open);
  $("#scrim").hidden = !open;
  $("#open-nav").setAttribute("aria-expanded", String(open));
  if (open) $("#sidebar nav a")?.focus({preventScroll: true});
}
$("#open-nav").addEventListener("click", () => setDrawer(true));
$("#close-nav").addEventListener("click", () => setDrawer(false));
$("#scrim").addEventListener("click", () => setDrawer(false));
document.addEventListener("keydown", event => { if (event.key === "Escape" && $("#sidebar").classList.contains("open")) setDrawer(false); });

/* ---------- Data refresh ---------- */
async function refresh() {
  if (fetching) return;
  fetching = true;
  try {
    const data = await api("/api/dashboard");
    const current = JSON.stringify(data);
    if (current !== lastDashboard) {
      const previous = dashboard;
      dashboard = data;
      lastDashboard = current;
      renderChrome();
      renderEvents(false);
      renderRuns();
      announceFinished(previous);
      if (currentView === "briefing") renderBriefing(false);
      if (currentView === "settings" && settings) renderProviderList();
    }
  } catch (error) {
    if (!lastDashboard) $("#event-list").replaceChildren(el("p", "panel empty", error.message));
  } finally {
    fetching = false;
  }
}

function announceFinished(previous) {
  if (!previous.runs.length) return;
  const before = new Map(previous.runs.map(run => [run.id, run.status]));
  for (const run of dashboard.runs) {
    const was = before.get(run.id);
    if (!["queued", "running"].includes(was) || ["queued", "running"].includes(run.status)) continue;
    if (run.status === "complete") toast(run.name + " is ready · " + plural(run.article_count || 0, "article"));
    else if (run.status === "failed") toast(run.name + " failed: " + (run.error || "see the server log"), "error");
  }
}

function renderChrome() {
  const ready = dashboard.ready || {};
  $("#setup-banner").hidden = !ready.model || currentView === "settings";
  $("#setup-text").textContent = ready.model ? ready.model + " Briefings can't run until a model is connected." : "";
  const upcoming = dashboard.events.filter(e => e.next_run).sort((a, b) => a.next_run - b.next_run)[0];
  $("#cadence-name").textContent = upcoming ? upcoming.name : "Nothing scheduled";
  $("#cadence-when").textContent = upcoming
    ? timeOnly.format(new Date(upcoming.next_run * 1000)) + " · " + ago(upcoming.next_run)
    : "Turn on a schedule in Events.";
}

/* ---------- Events view ---------- */
function providerName(id) {
  if (id === null || id === undefined) return "Default model";
  return dashboard.providers.find(p => p.id === id)?.name || "Removed provider";
}
function activeRun(eventId) {
  return dashboard.runs.find(run => run.event_id === eventId && ["queued", "running"].includes(run.status));
}

function renderEvents(animate = true) {
  $("#event-count").textContent = plural(dashboard.events.length, "event");
  const container = $("#event-list");
  const focused = container.contains(document.activeElement) ? document.activeElement.dataset.focus : null;
  const cards = dashboard.events.map((event, index) => {
    const card = el("article", "event-card");
    const copy = el("div", "event-copy");
    const title = el("div", "event-label");
    const scheduled = event.enabled ? "Scheduled" : "Manual";
    title.append(el("h3", "", event.name), el("span", "pill " + scheduled.toLowerCase(), scheduled));
    const running = activeRun(event.id);
    if (running) title.append(el("span", "pill " + running.status, running.status === "running" ? "Running" : "Queued"));
    const days = event.days.length === 7 ? "Daily" : event.days.map(day => dayNames[day]).join(", ");
    const sourceCount = event.sources.split(/[,\n]/).filter(url => url.trim()).length;
    const facts = el("ul", "event-facts");
    const fact = (path, text) => { const li = el("li"); li.append(icon(path), el("span", "", text)); facts.append(li); };
    fact(icons.clock, event.enabled ? days + " · " + event.time + (event.timezone !== localZone ? " " + event.timezone : "")
      + (event.next_run ? " · next " + ago(event.next_run) : "") : "Runs when you press Run now");
    fact(icons.feed, plural(sourceCount, "source"));
    fact(icons.chip, providerName(event.provider));
    fact(icons.mail, event.email ? "Web + email" : "Web only");
    copy.append(title, facts);
    const actions = el("div", "event-actions");
    const latest = dashboard.runs.find(run => run.event_id === event.id && run.readable);
    if (latest) {
      const read = el("a", "button secondary", "Read");
      read.href = "#briefing/" + latest.id;
      actions.append(read);
    }
    const edit = el("button", "button secondary", "Edit");
    edit.type = "button";
    edit.dataset.focus = "edit-" + event.id;
    edit.setAttribute("aria-label", "Edit " + event.name);
    edit.addEventListener("click", () => openEventEditor(event));
    const run = el("button", "button primary", running ? "Running…" : "Run now");
    run.type = "button";
    run.dataset.focus = "run-" + event.id;
    run.setAttribute("aria-label", "Run " + event.name + " now");
    run.disabled = Boolean(running);
    run.addEventListener("click", () => runEvent(event, run));
    actions.append(edit, run);
    card.append(copy, actions);
    return animate ? reveal(card, index) : card;
  });
  container.replaceChildren(...(cards.length ? cards : [el("p", "panel empty", "Create an event to get started.")]));
  if (focused) container.querySelector('[data-focus="' + focused + '"]')?.focus({preventScroll: true});
}

function runRow(run, index, animate) {
  const row = el("article", "activity-row");
  const copy = el("div");
  const title = el(run.readable ? "a" : "strong", "", run.name);
  if (run.readable) title.href = "#briefing/" + run.id;
  const details = [dateFormat.format(new Date(run.created * 1000))];
  if (run.article_count !== null) details.push(plural(run.article_count, "article"));
  if (run.issues) details.push(plural(run.issues, "source issue"));
  if (run.delivered) details.push("Emailed");
  copy.append(title, el("p", "meta", details.join(" · ")));
  if (run.error) copy.append(el("p", "meta", run.error));
  const status = run.status === "complete" ? "Ready" : run.status[0].toUpperCase() + run.status.slice(1);
  const side = el("div", "row-actions");
  side.append(el("span", "pill " + run.status, status));
  row.append(copy, side);
  return animate ? reveal(row, index) : row;
}

function renderRuns(animate = false) {
  const filter = $("#archive-filter");
  const selected = filter.value;
  const names = new Map(dashboard.events.map(event => [event.id, event.name]));
  dashboard.runs.forEach(run => { if (!names.has(run.event_id)) names.set(run.event_id, run.name); });
  const choices = [new Option("All events", "")];
  names.forEach((name, id) => choices.push(new Option(name, id)));
  filter.replaceChildren(...choices);
  if (names.has(Number(selected))) filter.value = selected;
  const recent = dashboard.runs.slice(0, 6).map((run, i) => runRow(run, i, animate));
  $("#recent").replaceChildren(...(recent.length ? recent : [el("p", "empty", "Run an event to see its progress here.")]));
  const archived = dashboard.runs.filter(run => !filter.value || run.event_id === Number(filter.value)).map((run, i) => runRow(run, i, animate));
  $("#archive-list").replaceChildren(...(archived.length ? archived : [el("p", "empty", "No editions yet.")]));
}
$("#archive-filter").addEventListener("change", () => renderRuns(true));

async function runEvent(event, trigger) {
  await busy(trigger, async () => {
    try {
      await api("/api/events/" + event.id + "/run", {weekly: false});
      toast(event.name + " queued. You'll get a notice here when it's ready.");
    } catch (error) {
      toast(error.message, "error");
    }
    await refresh();
  });
}

/* ---------- Event editor ---------- */
const eventForm = $("#event-form");
const eventDialog = $("#event-dialog");
dayNames.forEach((day, index) => {
  const label = el("label", "", day);
  const input = el("input");
  input.name = "days";
  input.type = "checkbox";
  input.value = index;
  input.setAttribute("aria-label", day);
  label.append(input);
  $("#weekdays").append(label);
});
for (const zone of [localZone, "UTC", "Asia/Kolkata", "America/New_York", "America/Los_Angeles", "Europe/London", "Europe/Berlin", "Asia/Singapore", "Asia/Tokyo", "Australia/Sydney"]) {
  const option = el("option");
  option.value = zone;
  $("#zones").append(option);
}

/* ---------- Source list editor ---------- */
let sourceLabels = {};
let sourceUrls = [];
function sourceText() { $("#source-urls").value = sourceUrls.join("\n"); }
function renderSources(highlight = []) {
  const list = $("#source-list");
  $("#source-count").textContent = sourceUrls.length ? "· " + plural(sourceUrls.length, "URL") : "";
  list.replaceChildren(...sourceUrls.map(url => {
    const li = el("li", highlight.includes(url) ? "flash" : "");
    const copy = el("span", "src");
    let host = url;
    try { host = new URL(url).hostname.replace(/^www\./, ""); } catch { /* shown raw */ }
    copy.append(el("b", "", sourceLabels[url] || host), link(url, url));
    const remove = el("button", "icon", "×");
    remove.type = "button";
    remove.setAttribute("aria-label", "Remove " + (sourceLabels[url] || url));
    remove.addEventListener("click", () => {
      li.classList.add("removing");
      li.addEventListener("animationend", () => {
        sourceUrls = sourceUrls.filter(u => u !== url);
        sourceText();
        renderSources();
        $("#source-input").focus();
      }, {once: true});
    });
    li.append(copy, remove);
    return li;
  }));
  $("#source-empty")?.remove();
  if (!sourceUrls.length) {
    const empty = el("p", "source-empty", "No sources yet. Add at least one feed or news page URL below.");
    empty.id = "source-empty";
    list.after(empty);
  }
  if (highlight.length) setTimeout(() => $$(".flash", list).forEach(node => node.classList.remove("flash")), 60);
  $("#source-restore").hidden = eventForm.elements.topic.value.trim().toLowerCase() !== "ai"
    || !presets?.ai || presets.ai.sources.split("\n").every(u => sourceUrls.includes(u));
}
function setSources(text) {
  sourceUrls = [...new Set((text || "").split(/[,\n]/).map(u => u.trim()).filter(Boolean))];
  sourceText();
  renderSources();
}
function addSources(text) {
  const candidates = text.split(/[\s,]+/).map(u => u.trim()).filter(Boolean);
  const bad = candidates.filter(u => !safeHref(u));
  const fresh = candidates.filter(u => safeHref(u) && !sourceUrls.includes(u));
  sourceUrls.push(...fresh);
  sourceText();
  renderSources(fresh);
  const dupes = candidates.length - bad.length - fresh.length;
  const notes = [];
  if (fresh.length) notes.push("Added " + plural(fresh.length, "source") + ". The other " + (sourceUrls.length - fresh.length) + " are unchanged.");
  if (dupes) notes.push(plural(dupes, "URL") + " already in the list.");
  if (bad.length) notes.push("Skipped " + bad.length + " that " + (bad.length === 1 ? "isn't" : "aren't") + " an http(s) URL: " + bad.slice(0, 2).join(", "));
  $("#event-error").textContent = bad.length ? notes.join(" ") : "";
  if (fresh.length || dupes) $("#source-count").textContent = "· " + plural(sourceUrls.length, "URL");
  if (!bad.length && notes.length) toast(notes.join(" "));
  return !bad.length;
}
$("#source-add").addEventListener("click", () => {
  const input = $("#source-input");
  if (!input.value.trim()) { input.focus(); return; }
  if (addSources(input.value)) input.value = "";
  input.focus();
});
$("#source-input").addEventListener("keydown", event => {
  if (event.key === "Enter") { event.preventDefault(); $("#source-add").click(); }
});
$("#source-input").addEventListener("paste", event => {
  const text = event.clipboardData?.getData("text") || "";
  if (/[\n,]/.test(text.trim())) {
    event.preventDefault();
    addSources(text);
  }
});
$("#source-restore").addEventListener("click", () => addSources(presets.ai.sources));
async function loadPresets() {
  try {
    presets ||= await api("/api/presets");
    sourceLabels = presets.labels || {};
  } catch { /* labels are cosmetic */ }
}

function updateWeekly() {
  const allowed = eventForm.elements.topic.value.trim().toLowerCase() === "ai";
  $("#weekly-label").hidden = !allowed;
  if (!allowed) eventForm.elements.weekly.checked = false;
}
function fillEventForm(data) {
  for (const key of ["name", "topic", "keywords", "window", "time", "timezone"]) eventForm.elements[key].value = data[key] ?? "";
  $("#source-input").value = "";
  setSources(data.sources);
  for (const key of ["enabled", "email", "weekly"]) eventForm.elements[key].checked = Boolean(data[key]);
  $$("[name=days]", eventForm).forEach(input => { input.checked = data.days.includes(Number(input.value)); });
  const select = $("#event-provider");
  select.replaceChildren(new Option("Default (from Settings)", ""), ...dashboard.providers.map(p => new Option(p.name + " · " + p.LLM_MODEL, p.id)));
  select.value = data.provider ?? "";
  updateWeekly();
}
function openEventEditor(event, focus = "name") {
  editingEvent = event?.id ?? null;
  eventForm.reset();
  $("#event-error").textContent = "";
  $("#dialog-title").textContent = event ? "Edit " + event.name : "New briefing event";
  $("#preset-label").hidden = Boolean(event);
  $$(".preset").forEach(b => b.setAttribute("aria-pressed", "false"));
  $("#delete-event").hidden = !event;
  fillEventForm(event || {name: "", topic: "", sources: "", keywords: "", window: 24, time: "08:00",
    timezone: localZone, days: [0, 1, 2, 3, 4, 5, 6], enabled: false, email: dashboard.ready?.email || false, weekly: false, provider: null});
  eventDialog.showModal();
  if (focus === "sources") $("#source-input").focus();
  else eventForm.elements[focus]?.focus();
  if (!presets) loadPresets().then(() => renderSources());
}
$("#new-event").addEventListener("click", () => openEventEditor());
eventForm.elements.topic.addEventListener("input", () => { updateWeekly(); renderSources(); });
$$(".preset").forEach(b => b.addEventListener("click", async () => {
  $$(".preset").forEach(other => other.setAttribute("aria-pressed", String(other === b)));
  const key = b.dataset.preset;
  if (!key) {
    fillEventForm({name: "", topic: "", sources: "", keywords: "", window: 24, time: "08:00", timezone: localZone,
      days: [0, 1, 2, 3, 4, 5, 6], enabled: false, email: false, weekly: false, provider: null});
    eventForm.elements.name.focus();
    return;
  }
  try {
    await loadPresets();
    fillEventForm({...presets[key], timezone: localZone, email: dashboard.ready?.email || false, provider: null});
  } catch (error) {
    $("#event-error").textContent = error.message;
  }
}));
eventForm.addEventListener("submit", async event => {
  event.preventDefault();
  if (!eventForm.reportValidity()) return;
  if ($("#source-input").value.trim() && !addSources($("#source-input").value)) return;
  $("#source-input").value = "";
  if (!sourceUrls.length) {
    $("#event-error").textContent = "Add at least one source URL.";
    $("#source-input").focus();
    return;
  }
  const form = new FormData(eventForm);
  const data = Object.fromEntries(form);
  data.window = Number(data.window);
  data.days = form.getAll("days").map(Number);
  data.provider = data.provider ? Number(data.provider) : null;
  for (const key of ["enabled", "email", "weekly"]) data[key] = eventForm.elements[key].checked;
  const submit = event.submitter || $("[type=submit]", eventForm);
  await busy(submit, async () => {
    try {
      await api(editingEvent === null ? "/api/events" : "/api/events/" + editingEvent, data);
      closeDialog(eventDialog);
      toast("Saved " + data.name + ".");
      await refresh();
    } catch (error) {
      $("#event-error").textContent = error.message;
    }
  });
});
$("#delete-event").addEventListener("click", async () => {
  if (!await confirmAction("Delete this event?", "Its schedule is removed. Past editions stay in History.")) return;
  try {
    await api("/api/events/" + editingEvent + "/delete", {});
    closeDialog(eventDialog);
    toast("Event deleted.");
    await refresh();
  } catch (error) {
    $("#event-error").textContent = error.message;
  }
});

/* ---------- Reader ---------- */
function readerTarget() {
  const pinned = /^#briefing\/(\d+)$/.exec(location.hash)?.[1];
  if (pinned) return Number(pinned);
  const readable = dashboard.runs.filter(run => run.readable);
  const forEvent = selectedEvent !== null ? readable.find(run => run.event_id === selectedEvent) : null;
  return (forEvent || readable[0])?.id ?? null;
}

async function loadEdition(id) {
  if (!editions.has(id)) editions.set(id, await api("/api/runs/" + id));
  return editions.get(id);
}

function fillSelect(select, values, allLabel) {
  const keep = select.value;
  select.replaceChildren(new Option(allLabel, ""), ...values.map(v => new Option(v, v)));
  select.value = values.includes(keep) ? keep : "";
}

function uniqueValues(articles, pick) {
  const set = new Set();
  articles.forEach(a => [].concat(pick(a) || []).forEach(v => v && set.add(v)));
  return [...set].sort();
}

function applyFilters(articles, prefix) {
  const category = $("#" + prefix + "-category").value;
  const signal = $("#" + prefix + "-signal").value;
  const audience = $("#" + prefix + "-audience").value;
  const search = $("#" + prefix + "-search").value.trim().toLowerCase();
  return articles.filter(a => (!category || a.category === category)
    && (!signal || a.signal === signal)
    && (!audience || (a.audiences || []).includes(audience))
    && (!search || [a.title, a.summary, a.source, a.writeup?.what_happened].join(" ").toLowerCase().includes(search)));
}

function citations(article) {
  const box = el("div", "citations");
  box.append(el("b", "", "Sources"));
  const refs = [{source: article.source || "Original article", link: article.link}, ...(article.also_seen_in || [])];
  refs.forEach((ref, i) => {
    const node = link(ref.link, ref.source || "Related coverage");
    if (node.tagName !== "A") return;
    const sup = el("sup", "", "[" + (i + 1) + "]");
    node.prepend(sup);
    node.append(" ↗");
    box.append(node);
  });
  return box;
}

function articleMeta(article, extra) {
  const meta = el("div", "article-meta");
  if (article.category) meta.append(el("span", "chip", article.category));
  if (article.signal) {
    const sig = el("span", "chip signal", article.signal);
    sig.dataset.signal = article.signal;
    meta.append(sig);
  }
  meta.append(el("span", "source", article.source || ""));
  if (article.timestamp) meta.append(el("span", "", "· " + ago(article.timestamp)));
  if (extra) meta.append(extra);
  const overall = article.scores?.overall;
  if (typeof overall === "number") {
    const badge = el("span", "overall", String(overall));
    badge.title = "Overall score out of 100";
    meta.append(badge);
  }
  return meta;
}

function articleCard(article, {format, ai, top, index, extra}) {
  if (format === "headlines") {
    const row = el("div", "headline-row");
    row.append(link(article.link, article.title || article.link), el("span", "meta", article.source || ""));
    const overall = article.scores?.overall;
    if (typeof overall === "number") row.append(el("span", "overall", String(overall)));
    return reveal(row, index);
  }
  const card = el("article", "article" + (top ? " top" : ""));
  if (top) card.append(el("div", "top-label", "Top signal"));
  card.append(articleMeta(article, extra));
  const h3 = el("h3");
  h3.append(link(article.link, article.title || article.link || "Untitled"));
  card.append(h3);
  const w = article.writeup || {};
  if (format === "quick" || !(w.what_happened || w.why_it_matters)) {
    card.append(el("p", "summary", article.summary || w.what_happened || ""));
  } else {
    const dl = el("dl", "writeup");
    for (const [key, label] of [["what_happened", "What happened"], ["why_it_matters", "Why it matters"],
      ["builder_takeaway", ai ? "Builder takeaway" : "What to watch"]]) {
      if (!w[key]) continue;
      const wrap = el("div");
      wrap.append(el("dt", "", label), el("dd", "", w[key]));
      dl.append(wrap);
    }
    card.append(dl);
    if (w.no_bs_read) {
      const nobs = el("p", "nobs");
      nobs.append(el("b", "", "No-BS read"), w.no_bs_read);
      card.append(nobs);
    }
    const scores = el("div", "scores");
    for (const [key, label] of scoreLabels) {
      const value = article.scores?.[key];
      if (typeof value !== "number") continue;
      const score = el("div", "score" + (key === "hype_risk" ? " hype" : ""));
      const head = el("span");
      head.append(el("span", "", label), el("b", "", String(value)));
      const bar = el("i");
      bar.style.setProperty("--v", value);
      score.append(head, bar);
      scores.append(score);
    }
    if (scores.childElementCount) card.append(scores);
    if (article.audiences?.length) {
      const aud = el("div", "audiences");
      article.audiences.forEach(a => aud.append(el("span", "", a)));
      card.append(aud);
    }
  }
  card.append(citations(article));
  return reveal(card, index);
}

function renderArticles(container, articles, options) {
  if (!articles.length) {
    container.replaceChildren(el("div", "panel empty", "No articles match these filters. Widen the filters or the time window."));
    return;
  }
  const sorted = [...articles].sort((a, b) => $("#f-sort").value === "new" && options.sortable
    ? (b.timestamp || 0) - (a.timestamp || 0)
    : (b.scores?.overall ?? -1) - (a.scores?.overall ?? -1));
  const nodes = sorted.map((article, i) => articleCard(article, {...options, top: options.highlightTop && i === 0, index: i,
    extra: options.extra?.(article)}));
  if (options.format === "headlines") {
    const list = el("div", "panel");
    list.append(...nodes);
    container.replaceChildren(list);
  } else {
    container.replaceChildren(...nodes);
  }
}

function setupSteps() {
  const ready = dashboard.ready || {};
  const box = el("div", "panel empty-state reveal");
  box.append(el("h2", "", "No briefings yet"), el("p", "", "Three steps to your first edition. After that, the latest briefing shows up here."));
  const steps = el("ol", "steps");
  const step = (done, text, href, label) => {
    const li = el("li", done ? "done" : "", text);
    if (href) { const a = el("a", "", label); a.href = href; li.append(a); }
    steps.append(li);
  };
  step(!ready.model, "Connect an AI provider", "#settings", "Settings");
  step(dashboard.events.length > 0, "Create or review a briefing event", "#events", "Events");
  step(false, "Press Run now. Editions appear here in a few minutes", "#events", "Run now");
  box.append(steps);
  return box;
}

let readerShown = null;
async function renderBriefing(animate = true) {
  const select = $("#edition-select");
  const eventsWithRuns = dashboard.events.filter(e => dashboard.runs.some(r => r.event_id === e.id && r.readable));
  select.replaceChildren(...eventsWithRuns.map(e => new Option(e.name, e.id)));
  select.closest("label").hidden = eventsWithRuns.length < 2;
  const id = readerTarget();
  const run = dashboard.runs.find(r => r.id === id);
  if (run) select.value = run.event_id;
  const event = dashboard.events.find(e => e.id === (run?.event_id ?? selectedEvent)) || dashboard.events[0];
  const runButton = $("#briefing-run");
  runButton.hidden = !event;
  const pending = event && activeRun(event.id);
  runButton.disabled = Boolean(pending);
  runButton.lastChild.textContent = pending ? (pending.status === "running" ? "Generating…" : "Queued…") : "Refresh now";

  if (id === null) {
    readerShown = null;
    $("#briefing-overline").textContent = "Briefing";
    $("#briefing-title").textContent = "Latest briefing";
    $("#briefing-lede").textContent = "Your newest edition, as structured, filterable stories with links to the original reporting.";
    $("#briefing-toolbar").hidden = true;
    $("#edition-actions").hidden = true;
    $("#briefing-stats").replaceChildren();
    $("#briefing-body").replaceChildren(setupSteps());
    return;
  }
  // Polling re-renders only when the edition changes, so cards don't re-animate every few seconds.
  if (readerShown === id && !animate) return;
  if (readerShown !== id) $("#briefing-body").replaceChildren(el("div", "skeleton"), el("div", "skeleton"), el("div", "skeleton short"));
  let edition;
  try {
    edition = await loadEdition(id);
  } catch (error) {
    $("#briefing-body").replaceChildren(el("p", "panel empty", error.message));
    return;
  }
  if (readerTarget() !== id) return;     // user navigated meanwhile
  readerShown = id;
  const ai = edition.topic === "ai";
  $("#briefing-overline").textContent = "Briefing #" + edition.id + " · " + longDate.format(new Date(edition.created * 1000));
  $("#briefing-title").textContent = edition.name;
  $("#briefing-lede").textContent = ai ? "What actually changed in AI, and what builders should care about. Source-tier transparent. Hype risk surfaced."
    : "The latest on " + edition.topic + ", with context and links to the original reporting.";
  $("#email-layout").href = "#report/" + edition.id;
  $("#edition-actions").hidden = !edition.readable;
  const articles = edition.articles || [];
  const stats = $("#briefing-stats");
  const statItems = [plural(articles.length, "article")];
  if (edition.sources) statItems.push(plural(edition.sources, "source"));
  if (edition.errors?.length) statItems.push(plural(edition.errors.length, "source issue"));
  stats.replaceChildren(...statItems.map(s => el("span", "", s)));
  if (!edition.structured) {
    $("#briefing-toolbar").hidden = true;
    const note = el("div", "panel empty-state reveal");
    note.append(el("h2", "", "Saved before the reader existed"), el("p", "", "This edition only has its email layout. New editions open here as interactive stories."));
    const a = el("a", "button primary", "Open the email layout");
    a.href = "#report/" + edition.id;
    note.append(a);
    $("#briefing-body").replaceChildren(note);
    return;
  }
  $("#briefing-toolbar").hidden = !articles.length;
  fillSelect($("#f-category"), uniqueValues(articles, a => a.category), "All categories");
  fillSelect($("#f-signal"), uniqueValues(articles, a => a.signal), "All signals");
  fillSelect($("#f-audience"), uniqueValues(articles, a => a.audiences), "All audiences");
  drawBriefing(edition);
}

function drawBriefing(edition) {
  const body = $("#briefing-body");
  const articles = edition.articles || [];
  if (!articles.length) {
    body.replaceChildren(el("div", "panel empty", "This edition found no new articles in its lookback window."));
    return;
  }
  const format = $("#f-format").value;
  renderArticles(body, applyFilters(articles, "f"), {format, ai: edition.topic === "ai", highlightTop: format === "full", sortable: true});
  const gaps = edition.skills?.gaps;
  if (gaps?.length && format !== "headlines") {
    const box = reveal(el("section", "skills"), articles.length);
    box.append(el("p", "overline", "Weekly skills gap"), el("h2", "", "Skills to look at"));
    if (edition.skills.summary) box.append(el("p", "lede", edition.skills.summary));
    const list = el("ol");
    gaps.forEach(g => { const li = el("li"); li.append(el("strong", "", g.skill), el("div", "meta", g.why || "")); list.append(li); });
    box.append(list);
    body.append(box);
  }
}
for (const id of ["#f-format", "#f-category", "#f-signal", "#f-audience", "#f-sort", "#f-search"]) {
  $(id).addEventListener(id === "#f-search" ? "input" : "change", () => {
    const edition = editions.get(readerShown);
    if (edition) drawBriefing(edition);
  });
}
$("#edition-select").addEventListener("change", event => {
  selectedEvent = Number(event.target.value);
  const latest = dashboard.runs.find(run => run.event_id === selectedEvent && run.readable);
  if (latest) location.hash = "#briefing/" + latest.id;
});
$("#briefing-run").addEventListener("click", () => {
  const id = readerTarget();
  const run = dashboard.runs.find(r => r.id === id);
  const event = dashboard.events.find(e => e.id === (run?.event_id ?? selectedEvent)) || dashboard.events[0];
  if (event) {
    selectedEvent = event.id;
    if (/^#briefing\/\d+$/.test(location.hash)) history.replaceState(null, "", "#briefing");
    runEvent(event, $("#briefing-run"));
  }
});
$("#email-edition").addEventListener("click", event => busy(event.currentTarget, async () => {
  try {
    const result = await api("/api/runs/" + readerShown + "/email", {});
    toast("Emailed to " + result.to + ".");
    await refresh();
  } catch (error) {
    toast(error.message, "error");
  }
}));

/* ---------- Explore ---------- */
async function renderExplore() {
  const eventSelect = $("#x-event");
  const keep = eventSelect.value;
  eventSelect.replaceChildren(new Option("All events", ""), ...dashboard.events.map(e => new Option(e.name, e.id)));
  eventSelect.value = keep;
  const query = new URLSearchParams();
  if ($("#x-window").value) query.set("hours", $("#x-window").value);
  if (eventSelect.value) query.set("event", eventSelect.value);
  const key = query.toString() + "|" + dashboard.runs.filter(r => r.readable).length;
  const body = $("#explore-body");
  if (exploreCache.key !== key) {
    body.replaceChildren(el("div", "skeleton short"), el("div", "skeleton short"), el("div", "skeleton short"));
    try {
      exploreCache = {key, articles: (await api("/api/explore?" + query)).articles};
    } catch (error) {
      body.replaceChildren(el("p", "panel empty", error.message));
      return;
    }
  }
  const articles = exploreCache.articles;
  fillSelect($("#x-category"), uniqueValues(articles, a => a.category), "All categories");
  fillSelect($("#x-signal"), uniqueValues(articles, a => a.signal), "All signals");
  fillSelect($("#x-audience"), uniqueValues(articles, a => a.audiences), "All audiences");
  const filtered = applyFilters(articles, "x");
  $("#explore-stats").replaceChildren(el("span", "", plural(filtered.length, "match") + " of " + articles.length),
    el("span", "", plural(new Set(articles.map(a => a.run_id)).size, "edition")));
  renderArticles(body, filtered, {format: "quick", ai: true, highlightTop: false, sortable: false, extra: article => {
    const chip = el("a", "chip edition-chip", article.edition);
    chip.href = "#briefing/" + article.run_id;
    chip.title = "Open this edition";
    return chip;
  }});
}
for (const id of ["#x-window", "#x-event", "#x-category", "#x-signal", "#x-audience"]) $(id).addEventListener("change", renderExplore);
$("#x-search").addEventListener("input", renderExplore);

/* ---------- Model picker ---------- */
function needsKey(type, url, requireFlag) {
  let host = "";
  try { host = new URL(url).hostname; } catch { /* incomplete URL */ }
  const ollamaCloud = type === "ollama" && (host === "ollama.com" || host.endsWith(".ollama.com"));
  return ["chatgpt", "anthropic", "opencode"].includes(type) || ollamaCloud || (type === "openai" && requireFlag);
}

/* Fetches the provider's model list into a <datalist>. `context()` returns the
   form's current provider, URL and typed key; the server falls back to the
   saved key only while provider and URL are unchanged. */
function modelPicker({input, list, status, button, context}) {
  let models = [];
  let token = 0;
  const describe = () => {
    const match = models.find(m => m.id === input.value.trim());
    if (match) {
      status.className = "hint model-status ok";
      status.textContent = "✓ " + (match.label !== match.id ? match.label + " · " : "") + (match.description || "Available on this provider.");
    } else if (models.length) {
      status.className = "hint model-status";
      status.textContent = plural(models.length, "model") + " available. Start typing or open the list to pick one.";
    }
  };
  async function load(quiet = false) {
    const ctx = context();
    if (!ctx.LLM_BASE_URL || !safeHref(ctx.LLM_BASE_URL)) {
      if (!quiet) { status.className = "hint model-status bad"; status.textContent = "Enter the API base URL first."; }
      return;
    }
    const mine = ++token;
    status.className = "hint model-status loading";
    status.textContent = "Loading models…";
    button.disabled = true;
    try {
      const result = await api("/api/providers/models", ctx);
      if (mine !== token) return;
      models = result.models;
      list.replaceChildren(...models.map(m => { const o = el("option"); o.value = m.id; if (m.label !== m.id) o.label = m.label; return o; }));
      if (!models.length) {
        status.className = "hint model-status bad";
        status.textContent = "The provider returned no models. Type the model ID instead.";
      } else {
        describe();
      }
    } catch (error) {
      if (mine !== token) return;
      models = [];
      list.replaceChildren();
      status.className = "hint model-status " + (quiet ? "" : "bad");
      status.textContent = quiet ? "Add the API key, then press Load models to see available IDs." : error.message;
    } finally {
      if (mine === token) button.disabled = false;
    }
  }
  button.addEventListener("click", () => load(false));
  input.addEventListener("input", describe);
  return {load, reset() { token++; models = []; list.replaceChildren(); status.textContent = ""; status.className = "hint model-status"; button.disabled = false; }};
}

/* ---------- Settings ---------- */
const settingsForm = $("#settings-form");
const fieldGroups = {
  "#provider-fields": [
    ["LLM_PROVIDER", "Provider", Object.fromEntries(Object.entries(defaultProviderTypes).map(([k, v]) => [k, v[0]]))],
    ["LLM_MODEL", "Model ID"], ["LLM_BASE_URL", "API base URL"], ["LLM_API_KEY", "API key", "secret"],
    ["REQUIRE_API_KEY", "Require a key for compatible gateways"],
  ],
  "#email-fields": [
    ["SMTP_HOST", "SMTP host"], ["SMTP_PORT", "SMTP port"], ["SMTP_USER", "SMTP username"],
    ["SMTP_PASS", "SMTP password", "secret"], ["SMTP_SECURITY", "Transport security", {ssl: "TLS (implicit)", starttls: "STARTTLS", plain: "Plain"}],
    ["MAIL_FROM", "Sender address"], ["MAIL_TO", "Recipient addresses", "text", "Separate multiple addresses with commas."],
  ],
  "#report-fields": [
    ["SAVE_PDF", "Save a PDF with each briefing"], ["ATTACH_PDF", "Attach the PDF to email"],
    ["PDF_DIR", "PDF folder", "text", "Leave blank to use the project folder."],
    ["CV_PATH", "CV PDF path", "text", "Leave blank to use cv.pdf in the project folder."],
    ["SKILLS_WINDOW_DAYS", "Skills lookback (days)"], ["MAX_SKILL_GAPS", "Maximum skills to suggest"],
    ["HISTORY_KEEP_DAYS", "AI news history retention (days)"],
  ],
  "#advanced-fields": [
    ["PER_FEED_LIMIT", "Articles per feed"], ["DETAIL_LIMIT", "Full cards per email"],
    ["CONCURRENCY", "Parallel article requests"], ["EXTRACT_TIMEOUT", "Gateway fallback timeout (seconds)"],
    ["MAX_CONTENT_CHARS", "Maximum article characters"], ["LLM_TIMEOUT", "Model timeout (seconds)", "number", "Use 0 for the provider default."],
    ["LLM_CONCURRENCY", "Parallel model requests", "number", "Use 0 for the provider default."],
    ["LLM_MAX_RETRIES", "Model retries"], ["LLM_BACKOFF_BASE", "Retry delay (seconds)", "decimal"],
    ["LLM_NUM_CTX", "Ollama context size"], ["LLM_MAX_NUM_CTX", "Ollama maximum context"],
    ["LLM_KEEP_ALIVE", "Ollama keep-alive"], ["LLM_STARTUP_WAIT", "Ollama startup wait (seconds)"],
    ["LLM_THINK", "Enable local Ollama thinking"],
  ],
};

function settingField(key, title, kind, hint) {
  const value = settings[key];
  if (kind === "secret") {
    const group = el("div", "secret-field");
    const label = el("label", "", title);
    const input = el("input");
    input.name = key;
    input.type = "password";
    input.autocomplete = "new-password";
    input.placeholder = value ? "Saved · leave blank to keep" : "Not set";
    input.addEventListener("input", () => { delete input.dataset.clear; });
    label.append(input);
    group.append(label);
    if (value) {
      const clear = el("button", "linkish", "Clear saved value");
      clear.type = "button";
      clear.addEventListener("click", () => { input.dataset.clear = "true"; input.value = ""; input.placeholder = "Will be cleared on save"; });
      group.append(clear);
    }
    return group;
  }
  if (typeof value === "boolean") {
    const label = el("label", "check switch");
    const input = el("input");
    input.type = "checkbox";
    input.name = key;
    input.checked = value;
    label.append(input, el("span"), " " + title);
    return label;
  }
  const label = el("label", "", title);
  const input = el(typeof kind === "object" ? "select" : "input");
  input.name = key;
  if (typeof kind === "object") {
    Object.entries(kind).forEach(([id, name]) => input.append(new Option(name, id)));
    input.value = value;
  } else {
    input.type = typeof value === "number" ? "number" : key === "LLM_BASE_URL" ? "url" : "text";
    input.step = kind === "decimal" ? "any" : "1";
    input.value = value;
    if (typeof value === "number" || key === "LLM_MODEL" || key === "LLM_BASE_URL") input.required = true;
  }
  label.append(input);
  if (hint) label.append(el("span", "hint", hint));
  if (key === "LLM_MODEL") {
    const row = el("span", "model-row");
    const list = el("datalist");
    list.id = "default-models";
    input.setAttribute("list", list.id);
    input.autocomplete = "off";
    input.placeholder = "Pick from the list or type an ID";
    const load = el("button", "button secondary small", "Load models");
    load.type = "button";
    label.replaceChildren(document.createTextNode(title), row);
    row.append(input, load);
    const status = el("span", "hint model-status");
    status.setAttribute("aria-live", "polite");
    label.append(status, list);
    defaultPicker = modelPicker({input, list, status, button: load, context: () => ({
      source: "default", LLM_PROVIDER: settingsForm.elements.LLM_PROVIDER.value,
      LLM_BASE_URL: settingsForm.elements.LLM_BASE_URL.value.trim(), LLM_API_KEY: settingsForm.elements.LLM_API_KEY.value.trim(),
    })});
  }
  return label;
}
let defaultPicker = null;

/* Marks the default key field required when the chosen provider needs one and
   no saved key would still apply. */
function syncDefaultKey() {
  const f = settingsForm.elements;
  const unchanged = f.LLM_PROVIDER.value === settings.LLM_PROVIDER && f.LLM_BASE_URL.value.trim() === settings.LLM_BASE_URL;
  const required = needsKey(f.LLM_PROVIDER.value, f.LLM_BASE_URL.value, f.REQUIRE_API_KEY.checked)
    && !(settings.LLM_API_KEY && unchanged && !f.LLM_API_KEY.dataset.clear);
  f.LLM_API_KEY.required = required;
  f.LLM_API_KEY.placeholder = required ? "Required for this provider" : settings.LLM_API_KEY && unchanged ? "Saved · leave blank to keep" : "Not needed for this provider";
}

function renderSettings() {
  for (const [selector, entries] of Object.entries(fieldGroups)) {
    $(selector).replaceChildren(...entries.map(entry => settingField(...entry)));
  }
  const provider = settingsForm.elements.LLM_PROVIDER;
  $("#provider-help").textContent = (defaultProviderTypes[provider.value] || defaultProviderTypes.auto)[3];
  provider.addEventListener("change", () => {
    const [, url, model, help] = defaultProviderTypes[provider.value];
    if (url) settingsForm.elements.LLM_BASE_URL.value = url;
    if (model) settingsForm.elements.LLM_MODEL.value = model;
    $("#provider-help").textContent = help;
    syncDefaultKey();
    defaultPicker.reset();
    defaultPicker.load(true);
  });
  settingsForm.elements.LLM_BASE_URL.addEventListener("change", () => { syncDefaultKey(); defaultPicker.load(true); });
  settingsForm.elements.LLM_API_KEY.addEventListener("change", () => { if (settingsForm.elements.LLM_API_KEY.value) defaultPicker.load(false); });
  settingsForm.elements.REQUIRE_API_KEY.addEventListener("change", syncDefaultKey);
  syncDefaultKey();
  defaultPicker.load(true);
  renderProviderList();
}

function renderProviderList() {
  const rows = dashboard.providers.map((p, i) => {
    const row = reveal(el("div", "provider-row"), i);
    const copy = el("div");
    copy.append(el("strong", "", p.name), el("span", "meta", (providerTypes[p.LLM_PROVIDER]?.[0] || p.LLM_PROVIDER) + " · " + p.LLM_MODEL));
    const users = dashboard.events.filter(e => e.provider === p.id).length;
    const edit = el("button", "button secondary small", "Edit");
    edit.type = "button";
    edit.addEventListener("click", () => openProviderEditor(p));
    row.append(copy, el("span", "pill", users ? "Used by " + plural(users, "event") : "Unused"), edit);
    return row;
  });
  $("#provider-list").replaceChildren(...(rows.length ? rows : [el("p", "meta", "No extra providers yet. Every event uses the default provider above.")]));
}

async function openSettings() {
  try {
    settings = await api("/api/settings");
    renderSettings();
    $("#settings-error").textContent = "";
  } catch (error) {
    $("#settings-error").textContent = error.message;
  }
}

function collectSettings() {
  const data = {};
  for (const input of $$("[name]", settingsForm)) {
    if (input.type === "checkbox") data[input.name] = input.checked;
    else if (input.type === "number") data[input.name] = Number(input.value);
    else data[input.name] = input.dataset.clear ? null : input.value;
  }
  return data;
}

async function saveSettings() {
  if (!settingsForm.reportValidity()) throw new Error("Fix the highlighted fields.");
  settings = await api("/api/settings", collectSettings());
  renderSettings();
  $("#settings-error").textContent = "";
  await refresh();
}

settingsForm.addEventListener("submit", async event => {
  event.preventDefault();
  const submit = event.submitter || $("[type=submit]", settingsForm);
  await busy(submit, async () => {
    try {
      await saveSettings();
      toast("Settings saved.");
    } catch (error) {
      $("#settings-error").textContent = error.message;
    }
  });
});

function showTest(node, result) {
  node.className = "test-result " + (result === null ? "pending" : result.ok ? "ok" : "bad");
  node.textContent = result === null ? "Contacting the model…" : (result.ok ? "✓ Connected. " : "✗ ") + result.message;
}

$("#test-default").addEventListener("click", event => busy(event.currentTarget, async () => {
  const out = $("#default-test");
  try {
    await saveSettings();
    showTest(out, null);
    showTest(out, await api("/api/providers/test", {provider: null}));
  } catch (error) {
    showTest(out, {ok: false, message: error.message});
  }
}));

/* ---------- Provider profiles ---------- */
const providerForm = $("#provider-form");
const providerDialog = $("#provider-dialog");
$("#provider-type").replaceChildren(...Object.entries(providerTypes).map(([k, v]) => new Option(v[0], k)));
function providerTypeChanged(fillDefaults) {
  const [, url, model, help] = providerTypes[providerForm.elements.LLM_PROVIDER.value];
  if (fillDefaults) {
    providerForm.elements.LLM_BASE_URL.value = url;
    providerForm.elements.LLM_MODEL.value = model;
  }
  $("#provider-type-help").textContent = help;
  $("#provider-require").hidden = providerForm.elements.LLM_PROVIDER.value !== "openai";
}
let editingProfile = null;
const providerPicker = modelPicker({
  input: providerForm.elements.LLM_MODEL, list: $("#provider-models"), status: $("#provider-model-status"),
  button: $("#provider-load-models"), context: () => ({
    source: editingProvider, LLM_PROVIDER: providerForm.elements.LLM_PROVIDER.value,
    LLM_BASE_URL: providerForm.elements.LLM_BASE_URL.value.trim(), LLM_API_KEY: providerForm.elements.LLM_API_KEY.value.trim(),
  }),
});
function syncProviderKey() {
  const f = providerForm.elements;
  const unchanged = editingProfile && f.LLM_PROVIDER.value === editingProfile.LLM_PROVIDER && f.LLM_BASE_URL.value.trim() === editingProfile.LLM_BASE_URL;
  const saved = Boolean(editingProfile?.LLM_API_KEY && unchanged);
  const required = needsKey(f.LLM_PROVIDER.value, f.LLM_BASE_URL.value, f.REQUIRE_API_KEY.checked) && !saved;
  f.LLM_API_KEY.required = required;
  f.LLM_API_KEY.placeholder = saved ? "Saved · leave blank to keep" : required ? "Required for this provider" : "Optional for this provider";
  $("#provider-key-hint").textContent = saved ? "Changing the provider or URL clears the saved key."
    : required ? "This provider rejects requests without a key. It's stored locally in .briefing/ and never shown again."
    : "Leave blank for a keyless local server.";
}
$("#provider-type").addEventListener("change", () => { providerTypeChanged(true); syncProviderKey(); providerPicker.reset(); providerPicker.load(true); });
providerForm.elements.LLM_BASE_URL.addEventListener("change", () => { syncProviderKey(); providerPicker.load(true); });
providerForm.elements.LLM_API_KEY.addEventListener("change", () => { if (providerForm.elements.LLM_API_KEY.value) providerPicker.load(false); });
providerForm.elements.REQUIRE_API_KEY.addEventListener("change", syncProviderKey);

function openProviderEditor(profile) {
  editingProvider = profile?.id ?? null;
  providerForm.reset();
  $("#provider-error").textContent = "";
  $("#provider-test").textContent = "";
  $("#provider-test").className = "test-result dialog-result";
  $("#provider-title").textContent = profile ? "Edit " + profile.name : "Add a provider";
  $("#delete-provider").hidden = !profile;
  const data = profile || {name: "", LLM_PROVIDER: "chatgpt", LLM_BASE_URL: providerTypes.chatgpt[1], LLM_MODEL: providerTypes.chatgpt[2], REQUIRE_API_KEY: true, LLM_API_KEY: false};
  for (const key of ["name", "LLM_PROVIDER", "LLM_BASE_URL", "LLM_MODEL"]) providerForm.elements[key].value = data[key];
  providerForm.elements.REQUIRE_API_KEY.checked = data.REQUIRE_API_KEY;
  editingProfile = profile || null;
  providerTypeChanged(false);
  syncProviderKey();
  providerPicker.reset();
  providerPicker.load(true);
  providerDialog.showModal();
  providerForm.elements.name.focus();
}
$("#add-provider").addEventListener("click", () => openProviderEditor());

async function saveProvider() {
  if (!providerForm.reportValidity()) throw new Error("Fill in the required fields.");
  const data = Object.fromEntries(new FormData(providerForm));
  data.REQUIRE_API_KEY = providerForm.elements.REQUIRE_API_KEY.checked;
  const saved = await api(editingProvider === null ? "/api/providers" : "/api/providers/" + editingProvider, data);
  editingProvider = saved.id;
  editingProfile = saved;
  $("#delete-provider").hidden = false;
  providerForm.elements.LLM_API_KEY.value = "";
  syncProviderKey();
  await refresh();
  return saved;
}
providerForm.addEventListener("submit", async event => {
  event.preventDefault();
  await busy(event.submitter || $("[type=submit]", providerForm), async () => {
    try {
      const saved = await saveProvider();
      closeDialog(providerDialog);
      toast("Saved " + saved.name + ".");
    } catch (error) {
      $("#provider-error").textContent = error.message;
    }
  });
});
$("#test-provider").addEventListener("click", event => busy(event.currentTarget, async () => {
  const out = $("#provider-test");
  $("#provider-error").textContent = "";
  try {
    const saved = await saveProvider();
    showTest(out, null);
    out.classList.add("dialog-result");
    showTest(out, await api("/api/providers/test", {provider: saved.id}));
    out.classList.add("dialog-result");
  } catch (error) {
    $("#provider-error").textContent = error.message;
  }
}));
$("#delete-provider").addEventListener("click", async () => {
  if (!await confirmAction("Delete this provider?", "Its saved API key is removed. Events must not be using it.")) return;
  try {
    await api("/api/providers/" + editingProvider + "/delete", {});
    closeDialog(providerDialog);
    toast("Provider deleted.");
    await refresh();
    renderProviderList();
  } catch (error) {
    $("#provider-error").textContent = error.message;
  }
});

/* ---------- Router ---------- */
function viewFor(hash) {
  if (/^#briefing(\/\d+)?$/.test(hash) || hash === "" || hash === "#") return "briefing";
  if (/^#report\/\d+$/.test(hash)) return "report";
  const name = hash.slice(1);
  return ["explore", "archive", "events", "settings"].includes(name) ? name : "briefing";
}

function showView() {
  const view = viewFor(location.hash);
  const changed = view !== currentView;
  currentView = view;
  $$("main > .view").forEach(section => { section.hidden = section.id !== "view-" + view; });
  const navView = view === "report" ? "briefing" : view;
  $$("nav a").forEach(a => a.dataset.view === navView ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current"));
  renderChrome();
  if (view === "briefing") { readerShown = null; renderBriefing(true); }
  if (view === "explore") renderExplore();
  if (view === "archive") renderRuns(true);
  if (view === "events") { renderEvents(true); renderRuns(true); }
  if (view === "settings") openSettings();
  const report = /^#report\/(\d+)$/.exec(location.hash);
  if (report) {
    const url = "/reports/" + report[1];
    $("#open-report").href = url;
    $("#report-frame").src = url;
    $("#report-back").href = "#briefing/" + report[1];
    $("#report-title").textContent = dashboard.runs.find(r => r.id === Number(report[1]))?.name || "Briefing";
  } else {
    $("#report-frame").removeAttribute("src");
  }
  if (changed) window.scrollTo({top: 0});
  document.title = ({briefing: "Briefing", explore: "Explore", archive: "History", events: "Events", settings: "Settings", report: "Email layout"})[view] + " · Dispatch";
}

function route() {
  setDrawer(false);
  if (document.startViewTransition && !matchMedia("(prefers-reduced-motion: reduce)").matches && currentView) {
    document.startViewTransition(showView);
  } else {
    showView();
  }
}

window.addEventListener("hashchange", route);
refresh().then(route);
setInterval(refresh, 4000);
// Keep relative times ("next in 3 hours") honest without a server round trip.
setInterval(renderChrome, 60000);
