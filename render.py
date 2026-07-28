# src/news_email.py
"""Rich, email-safe HTML renderer for the News Briefing digest.

Mirrors the "AI with Aish — No-BS AI Briefing" presentation: dark charcoal
theme, amber primary, signal-color-coded pills, monospace uppercase section
labels (WHAT HAPPENED / WHY IT MATTERS / BUILDER TAKEAWAY), a boxed NO-BS READ,
a SIGNAL SCORES bar list, a Top Signal hero, and a "What actually changed"
summary.

Email-safe by construction: table layout, all-inline styles + bgcolor attrs,
no JS, no external CSS/fonts (system + monospace stacks), no color-mix/flex/
backdrop-filter. The same HTML is what the emailed digest renders as when
saved/printed to PDF.
"""
from __future__ import annotations

import html as _html
import re
import time
from typing import Dict, List

# Clean, light, print-friendly palette (readability first — not theme-matched).
_BG = "#f4f5f7"
_CARD = "#ffffff"
_CARD_SOFT = "#f7f8fa"     # boxed NO-BS read / inner panels
_BORDER = "#e3e5ea"
_TEXT = "#1f2329"
_MUTED = "#6b7280"
_PRIMARY = "#2563eb"       # restrained accent (Top Signal, score bars)
_TRACK = "#e9ebef"
_FONT = ("-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Inter,"
         "Helvetica,Arial,sans-serif")
_MONO = "ui-monospace,'SFMono-Regular',Menlo,Consolas,monospace"

# Signal → color: color-coding by importance is functional (kept), tuned to be
# legible on a white background / in print.
_SIGNAL_COLOR = {
    "HIGH SIGNAL": "#d97706",
    "BUILDER USEFUL": "#0f766e",
    "WATCH": "#6b7280",
    "RESEARCH SIGNAL": "#6d28d9",
    "BUSINESS SIGNAL": "#c2410c",
    "POLICY SIGNAL": "#92651c",
    "NOISE": "#be185d",
}


def _esc(s) -> str:
    return _html.escape("" if s is None else str(s), quote=True)


def _safe_url(u: str) -> str:
    u = (u or "").strip()
    return _esc(u) if u[:7].lower() in ("http://", "https:") else ""


def _rel_time(ts) -> str:
    if not ts:
        return ""
    try:
        d = time.time() - float(ts)
    except (TypeError, ValueError):
        return ""
    if d < 0:
        return ""
    if d < 3600:
        return f"{max(1, int(d // 60))}m ago"
    if d < 86400:
        return f"{int(d // 3600)}h ago"
    return f"{int(d // 86400)}d ago"


def _sig_color(signal: str) -> str:
    return _SIGNAL_COLOR.get((signal or "").upper(), _MUTED)


def _pill(text: str, color: str, filled: bool = False) -> str:
    if not text:
        return ""
    if filled:
        style = f"background:{color};color:#ffffff;border:1px solid {color};"
    else:
        style = f"background:transparent;color:{color};border:1px solid {color};"
    return (f'<span style="display:inline-block;{style}border-radius:4px;'
            f'padding:2px 7px;font:600 9.5px {_MONO};letter-spacing:.08em;'
            f'text-transform:uppercase;margin:0 4px 4px 0;white-space:nowrap">{_esc(text)}</span>')


def _label(text: str, color: str = _MUTED) -> str:
    return (f'<div style="font:600 9.5px {_MONO};letter-spacing:.16em;'
            f'text-transform:uppercase;color:{color};margin:12px 0 3px">{_esc(text)}</div>')


def _para(text: str, color: str = _TEXT) -> str:
    return (f'<div style="font:400 13.5px/1.55 {_FONT};color:{color}">{_esc(text)}</div>')


def _overall(value) -> str:
    try:
        v = int(round(float(value)))
    except (TypeError, ValueError):
        v = 0
    return (f'<span style="font:600 9.5px {_MONO};letter-spacing:.12em;color:{_MUTED}">OVERALL</span>'
            f'&nbsp;<span style="font:700 15px {_FONT};color:{_PRIMARY}">{v}</span>')


def _score_bar(label: str, value, emphasize: bool = False) -> str:
    try:
        v = max(0, min(100, int(round(float(value)))))
    except (TypeError, ValueError):
        v = 0
    rest = 100 - v
    color = _PRIMARY
    fill = (f'<td bgcolor="{color}" style="height:6px;width:{v}%;background:{color};'
            f'border-radius:3px;font-size:0;line-height:0">&nbsp;</td>') if v else ""
    gap = (f'<td style="font-size:0;line-height:0;width:{rest}%">&nbsp;</td>') if rest else ""
    lbl_color = _TEXT if emphasize else _MUTED
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" '
        'style="width:100%;border-collapse:collapse;margin:4px 0"><tr>'
        f'<td style="width:74px;font:600 9px {_MONO};letter-spacing:.06em;'
        f'text-transform:uppercase;color:{lbl_color};white-space:nowrap">{_esc(label)}</td>'
        '<td style="padding:0 8px"><table role="presentation" cellpadding="0" '
        f'cellspacing="0" bgcolor="{_TRACK}" style="width:100%;background:{_TRACK};'
        f'border-radius:3px;border-collapse:collapse"><tr>{fill}{gap}</tr></table></td>'
        f'<td style="width:22px;text-align:right;font:700 11px {_MONO};color:{_TEXT if emphasize else _MUTED}">{v}</td>'
        '</tr></table>'
    )


def _scores_block(scores: Dict) -> str:
    if not scores:
        return ""
    rows = (
        _score_bar("Practical", scores.get("practical"))
        + _score_bar("Technical", scores.get("technical"))
        + _score_bar("Market", scores.get("market"))
        + _score_bar("Hype risk", scores.get("hype_risk"))
        + _score_bar("Urgency", scores.get("urgency"))
        + _score_bar("Overall", scores.get("overall"), emphasize=True)
    )
    return _label("Signal scores") + rows


def _no_bs_box(text: str) -> str:
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" bgcolor="{_CARD_SOFT}" '
        f'style="width:100%;background:{_CARD_SOFT};border:1px solid {_BORDER};'
        f'border-radius:8px;margin-top:12px;border-collapse:separate">'
        f'<tr><td style="padding:10px 12px">{_label("No-BS read")}{_para(text)}</td></tr></table>'
    )


def _card(a: Dict) -> str:
    href = _safe_url(a.get("link"))
    title = _esc(a.get("title") or a.get("link") or "Untitled")
    title_html = (f'<a href="{href}" style="color:{_TEXT};text-decoration:none">{title}</a>'
                  if href else title)
    source = _esc(a.get("source") or "")
    src_html = (f'<a href="{href}" style="color:{_PRIMARY};text-decoration:none">{source} &#8599;</a>'
                if href and source else source)
    rel = _rel_time(a.get("timestamp"))
    scores = a.get("scores") or {}
    signal = a.get("signal") or ""

    pills = _pill(signal, _sig_color(signal), filled=True) + _pill(a.get("category") or "", "#a79f90")
    for t in (a.get("status_tags") or []):
        pills += _pill(t, _MUTED)
    rs = a.get("run_status")
    if rs and rs not in ("unchanged", None):
        pills += _pill(rs, _PRIMARY, filled=True)

    w = a.get("writeup") or {}
    body = ""
    if w.get("what_happened"):
        body += _label("What happened") + _para(w["what_happened"])
    if w.get("why_it_matters"):
        body += _label("Why it matters") + _para(w["why_it_matters"])
    if w.get("builder_takeaway"):
        body += _label("Builder takeaway") + _para(w["builder_takeaway"])
    if not body and a.get("summary"):
        body = _para(a["summary"])
    if w.get("no_bs_read"):
        body += _no_bs_box(w["no_bs_read"])

    also = [x.get("source", "") for x in (a.get("also_seen_in") or []) if x.get("source")]
    also_html = (f'<div style="font:400 11px {_FONT};color:{_MUTED};margin-top:10px">'
                 f'also reported by: {_esc(", ".join(also))}</div>') if also else ""

    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" bgcolor="{_CARD}" '
        f'style="width:100%;border-collapse:separate;background:{_CARD};'
        f'border:1px solid {_BORDER};border-radius:12px;margin:0 0 14px">'
        f'<tr><td style="padding:16px 18px">'
        # pills row + OVERALL
        f'<table role="presentation" cellpadding="0" cellspacing="0" style="width:100%;border-collapse:collapse"><tr>'
        f'<td valign="top">{pills}</td>'
        f'<td valign="top" style="text-align:right;white-space:nowrap;padding-left:10px">{_overall(scores.get("overall"))}</td>'
        f'</tr></table>'
        f'<div style="font:600 17px/1.35 {_FONT};color:{_TEXT};margin-top:8px">{title_html}</div>'
        f'<div style="font:500 11.5px {_MONO};margin-top:4px">{src_html}'
        f'{("<span style=\"color:" + _MUTED + "\"> &nbsp;·&nbsp; " + rel + "</span>") if rel else ""}</div>'
        f'{body}'
        f'<div style="margin-top:14px">{_scores_block(scores)}</div>'
        f'{also_html}'
        f'</td></tr></table>'
    )


def _top_signal(a: Dict) -> str:
    href = _safe_url(a.get("link"))
    title = _esc(a.get("title") or "")
    title_html = f'<a href="{href}" style="color:{_TEXT};text-decoration:none">{title}</a>' if href else title
    scores = a.get("scores") or {}
    txt = _esc((a.get("writeup") or {}).get("no_bs_read")
               or (a.get("writeup") or {}).get("why_it_matters") or a.get("summary") or "")
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" bgcolor="{_CARD}" '
        f'style="width:100%;border-collapse:separate;background:{_CARD};'
        f'border:1px solid {_PRIMARY};border-radius:12px;margin:0 0 22px">'
        f'<tr><td style="padding:16px 18px;border-top:3px solid {_PRIMARY};border-radius:12px">'
        f'<div style="font:700 9.5px {_MONO};letter-spacing:.2em;text-transform:uppercase;color:{_PRIMARY}">Top signal</div>'
        f'<div style="font:700 19px/1.3 {_FONT};color:{_TEXT};margin-top:8px">{title_html}</div>'
        f'{("<div style=\"font:400 13.5px/1.55 " + _FONT + ";color:" + _MUTED + ";margin-top:8px\">" + txt + "</div>") if txt else ""}'
        f'<table role="presentation" cellpadding="0" cellspacing="0" style="width:100%;margin-top:12px;border-collapse:collapse"><tr>'
        f'<td style="font:600 10px {_MONO};letter-spacing:.1em;text-transform:uppercase;color:{_MUTED}">{_esc(a.get("source") or "")}</td>'
        f'<td style="text-align:right;white-space:nowrap">{_overall(scores.get("overall"))}</td>'
        f'</tr></table>'
        f'</td></tr></table>'
    )


def _what_changed(arts: List[Dict], n: int = 5) -> str:
    items = arts[:n]
    if not items:
        return ""
    rows = ""
    for i, a in enumerate(items, 1):
        w = a.get("writeup") or {}
        line = w.get("what_happened") or a.get("summary") or a.get("title") or ""
        rows += (
            f'<tr><td valign="top" style="width:26px;font:700 11px {_MONO};color:{_PRIMARY};padding:6px 0">'
            f'{i:02d}</td>'
            f'<td style="padding:6px 0;font:400 13px/1.5 {_FONT};color:{_TEXT}">{_esc(line)}</td></tr>'
        )
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" bgcolor="{_CARD}" '
        f'style="width:100%;background:{_CARD};border:1px solid {_BORDER};border-radius:12px;'
        f'margin:0 0 22px;border-collapse:separate"><tr><td style="padding:14px 18px">'
        f'{_label("What actually changed")}'
        f'<table role="presentation" cellpadding="0" cellspacing="0" style="width:100%;border-collapse:collapse">{rows}</table>'
        f'</td></tr></table>'
    )


def _more_row(a: Dict) -> str:
    href = _safe_url(a.get("link"))
    title = _esc(a.get("title") or a.get("link") or "")
    title_html = f'<a href="{href}" style="color:{_TEXT};text-decoration:none">{title}</a>' if href else title
    ov = (a.get("scores") or {}).get("overall", "")
    sig = a.get("signal") or ""
    return (
        f'<tr><td style="padding:8px 0;border-bottom:1px solid {_BORDER}">'
        f'<table role="presentation" cellpadding="0" cellspacing="0" style="width:100%"><tr>'
        f'<td style="width:30px;font:700 12px {_MONO};color:{_PRIMARY}">{_esc(ov)}</td>'
        f'<td style="font:500 13px {_FONT};color:{_TEXT}">{title_html}'
        f'<span style="font:600 10px {_MONO};color:{_sig_color(sig)};margin-left:8px">{_esc(sig)}</span></td>'
        f'<td style="text-align:right;font:400 10.5px {_MONO};color:{_MUTED};white-space:nowrap">{_esc(a.get("source") or "")}</td>'
        f'</tr></table></td></tr>'
    )


def render_news_html(news: Dict, *, title: str = "AI News Briefing",
                     detail_limit: int = 20) -> str:
    """Render a NewsResearcher result dict into an email-safe HTML briefing."""
    from datetime import datetime
    arts: List[Dict] = list(news.get("articles") or [])
    now = datetime.now()
    date_label = now.strftime(f"%A, %B {now.day}, %Y")
    n = len(arts)
    srcs = len(news.get("input_sources") or [])
    errs = len(news.get("errors") or [])

    head = (
        f'<div style="font:700 10px {_MONO};letter-spacing:.22em;text-transform:uppercase;color:{_PRIMARY}">'
        f'No-BS Briefing &nbsp;·&nbsp; {_esc(date_label)}</div>'
        f'<div style="font:700 27px/1.15 {_FONT};color:{_TEXT};margin-top:8px">{_esc(title)}</div>'
        f'<div style="font:400 13.5px/1.5 {_FONT};color:{_MUTED};margin-top:8px">'
        f'What actually changed in AI, and what builders should care about. '
        f'Source-tier transparent. Hype risk surfaced.</div>'
        f'<div style="font:500 11.5px {_MONO};color:{_MUTED};margin-top:8px;letter-spacing:.04em">'
        f'{n} ARTICLE{"S" if n != 1 else ""} · {srcs} SOURCE{"S" if srcs != 1 else ""}'
        f'{f" · {errs} SOURCE ISSUE" + ("S" if errs != 1 else "") if errs else ""}</div>'
    )

    if not arts:
        inner = (head + f'<div style="font:400 14px {_FONT};color:{_MUTED};margin-top:24px">'
                 'No articles matched. Check source availability or widen the time window.</div>')
    else:
        body = _top_signal(arts[0]) + _what_changed(arts)
        body += (f'<div style="font:600 10px {_MONO};letter-spacing:.16em;text-transform:uppercase;'
                 f'color:{_MUTED};margin:0 0 10px">Main updates &nbsp;·&nbsp; '
                 f'{min(len(arts), detail_limit)} of {len(arts)}</div>')
        body += "".join(_card(a) for a in arts[:detail_limit])
        rest = arts[detail_limit:]
        if rest:
            rows = "".join(_more_row(a) for a in rest)
            body += (
                f'<div style="font:600 10px {_MONO};letter-spacing:.16em;text-transform:uppercase;'
                f'color:{_MUTED};margin:14px 0 8px">More headlines ({len(rest)})</div>'
                f'<table role="presentation" cellpadding="0" cellspacing="0" bgcolor="{_CARD}" '
                f'style="width:100%;background:{_CARD};border:1px solid {_BORDER};border-radius:12px;'
                f'padding:2px 16px;border-collapse:separate">{rows}</table>'
            )
        inner = head + f'<div style="margin-top:24px">{body}</div>'

    footer = (f'<div style="font:400 11px {_FONT};color:{_MUTED};text-align:center;'
              f'margin-top:26px;padding-top:16px;border-top:1px solid {_BORDER}">'
              f'Generated by Odysseus · News Briefing</div>')

    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="color-scheme" content="light">'
        f'<title>{_esc(title)}</title></head>'
        f'<body style="margin:0;padding:0;background:{_BG};background-color:{_BG}">'
        f'<table role="presentation" cellpadding="0" cellspacing="0" width="100%" bgcolor="{_BG}" '
        f'style="width:100%;background:{_BG};border-collapse:collapse">'
        f'<tr><td align="center" style="padding:30px 14px">'
        f'<table role="presentation" cellpadding="0" cellspacing="0" width="680" '
        f'style="width:100%;max-width:680px;text-align:left">'
        f'<tr><td>{inner}{footer}</td></tr></table>'
        f'</td></tr></table></body></html>'
    )
