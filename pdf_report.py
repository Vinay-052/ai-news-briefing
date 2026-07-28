"""PDF rendering for the briefing.

Built directly from the structured article data with fpdf2 rather than by
converting the email HTML: fpdf2 is pure Python (no cairo/pango/wkhtmltopdf), so
it installs cleanly on a Raspberry Pi, and a purpose-built print layout beats
whatever an HTML-to-PDF converter makes of a table-based email.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from fpdf import FPDF

# Print palette (matches the email's intent: restrained, legible on paper).
_TEXT = (31, 35, 41)
_MUTED = (110, 116, 126)
_RULE = (222, 226, 232)
_ACCENT = (37, 99, 235)
_TRACK = (232, 235, 240)

_SIGNAL_RGB = {
    "HIGH SIGNAL": (217, 119, 6),
    "BUILDER USEFUL": (15, 118, 110),
    "WATCH": (107, 114, 128),
    "RESEARCH SIGNAL": (109, 40, 217),
    "BUSINESS SIGNAL": (194, 65, 12),
    "POLICY SIGNAL": (146, 101, 28),
    "NOISE": (190, 24, 93),
}

# fpdf2's built-in fonts are latin-1 only; transliterate rather than ship a TTF.
_SUBS = {
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", "…": "...", "•": "-",
    "→": "->", "←": "<-", " ": " ", "‑": "-",
    "′": "'", "″": '"', "€": "EUR", "≥": ">=", "≤": "<=",
}


def _txt(s) -> str:
    """Make text safe for fpdf2's core fonts."""
    s = "" if s is None else str(s)
    for bad, good in _SUBS.items():
        s = s.replace(bad, good)
    return s.encode("latin-1", "replace").decode("latin-1")


def _rel_time(ts) -> str:
    if not ts:
        return ""
    import time
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


class _Doc(FPDF):
    def __init__(self, title: str):
        super().__init__(format="A4", unit="mm")
        self._title = title
        self.set_auto_page_break(auto=True, margin=16)
        self.set_margins(15, 15, 15)
        self.set_title(title)

    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "", 7)
        self.set_text_color(*_MUTED)
        self.cell(0, 5, _txt(f"{self._title}  |  page {self.page_no()}"), align="C")

    # -- helpers ----------------------------------------------------------
    def label(self, text: str, color=None):
        self.set_font("Helvetica", "B", 6.5)
        self.set_text_color(*(color or _MUTED))
        self.cell(0, 3.6, _txt(text.upper()), new_x="LMARGIN", new_y="NEXT")

    def para(self, text: str, size: float = 8.6, color=None, indent: float = 0.0):
        if not text:
            return
        self.set_font("Helvetica", "", size)
        self.set_text_color(*(color or _TEXT))
        if indent:
            self.set_x(self.l_margin + indent)
        self.multi_cell(self.epw - indent, 4.0, _txt(text), new_x="LMARGIN", new_y="NEXT")

    def rule(self, gap_before: float = 3.0, gap_after: float = 3.0):
        self.ln(gap_before)
        self.set_draw_color(*_RULE)
        self.set_line_width(0.2)
        y = self.get_y()
        self.line(self.l_margin, y, self.l_margin + self.epw, y)
        self.ln(gap_after)

    def tag(self, text: str, rgb, filled: bool = True) -> float:
        """Draw a small pill at the cursor; returns its width."""
        if not text:
            return 0.0
        self.set_font("Helvetica", "B", 6)
        w = self.get_string_width(_txt(text)) + 3.4
        x, y = self.get_x(), self.get_y()
        if filled:
            self.set_fill_color(*rgb)
            self.rect(x, y, w, 3.9, style="F")
            self.set_text_color(255, 255, 255)
        else:
            self.set_draw_color(*rgb)
            self.set_line_width(0.2)
            self.rect(x, y, w, 3.9, style="D")
            self.set_text_color(*rgb)
        self.set_xy(x + 1.7, y + 0.45)
        self.cell(w - 3.4, 3.0, _txt(text))
        self.set_xy(x + w + 1.4, y)
        return w + 1.4

    def score_bar(self, label: str, value, width: float = 26.0, emphasize: bool = False):
        try:
            v = max(0, min(100, int(round(float(value)))))
        except (TypeError, ValueError):
            v = 0
        x, y = self.get_x(), self.get_y()
        self.set_font("Helvetica", "B" if emphasize else "", 6)
        self.set_text_color(*(_TEXT if emphasize else _MUTED))
        self.set_xy(x, y)
        self.cell(15, 3.4, _txt(label.upper()))
        bx = x + 15
        self.set_fill_color(*_TRACK)
        self.rect(bx, y + 1.0, width, 1.6, style="F")
        if v:
            self.set_fill_color(*_ACCENT)
            self.rect(bx, y + 1.0, width * v / 100.0, 1.6, style="F")
        self.set_xy(bx + width + 1.5, y)
        self.set_font("Helvetica", "B", 6)
        self.set_text_color(*_TEXT)
        self.cell(7, 3.4, _txt(str(v)))
        self.set_xy(x, y + 3.6)


def _header(pdf: _Doc, news: Dict, title: str):
    arts = news.get("articles") or []
    now = datetime.now()
    pdf.set_font("Helvetica", "B", 7)
    pdf.set_text_color(*_ACCENT)
    pdf.cell(0, 4, _txt(f"NO-BS BRIEFING  |  {now.strftime('%A, %B %d, %Y  %H:%M')}"),
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)
    pdf.set_font("Helvetica", "B", 19)
    pdf.set_text_color(*_TEXT)
    pdf.cell(0, 8, _txt(title), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(*_MUTED)
    errs = len(news.get("errors") or [])
    line = (f"{len(arts)} article(s) from {len(news.get('input_sources') or [])} source(s)"
            + (f"  |  {errs} source issue(s)" if errs else ""))
    pdf.cell(0, 4, _txt(line), new_x="LMARGIN", new_y="NEXT")
    pdf.rule(2.5, 2.0)


def _top_signal(pdf: _Doc, a: Dict):
    y0 = pdf.get_y()
    pdf.set_fill_color(*_ACCENT)
    pdf.rect(pdf.l_margin, y0, 1.1, 16, style="F")
    pdf.set_x(pdf.l_margin + 4)
    pdf.set_font("Helvetica", "B", 6.5)
    pdf.set_text_color(*_ACCENT)
    pdf.cell(0, 3.6, _txt("TOP SIGNAL"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_x(pdf.l_margin + 4)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(*_TEXT)
    pdf.multi_cell(pdf.epw - 4, 5, _txt(a.get("title") or ""), new_x="LMARGIN", new_y="NEXT")
    w = a.get("writeup") or {}
    blurb = w.get("no_bs_read") or w.get("why_it_matters") or a.get("summary") or ""
    if blurb:
        pdf.set_x(pdf.l_margin + 4)
        pdf.set_font("Helvetica", "", 8.4)
        pdf.set_text_color(*_MUTED)
        pdf.multi_cell(pdf.epw - 4, 4, _txt(blurb), new_x="LMARGIN", new_y="NEXT")
    pdf.set_x(pdf.l_margin + 4)
    pdf.set_font("Helvetica", "B", 7)
    pdf.set_text_color(*_ACCENT)
    ov = (a.get("scores") or {}).get("overall", "")
    pdf.cell(0, 4, _txt(f"{a.get('source') or ''}   OVERALL {ov}"), new_x="LMARGIN", new_y="NEXT")
    pdf.rule(2.5, 2.0)


def _what_changed(pdf: _Doc, arts: List[Dict], n: int = 5):
    items = arts[:n]
    if not items:
        return
    pdf.label("What actually changed")
    pdf.ln(0.8)
    for i, a in enumerate(items, 1):
        w = a.get("writeup") or {}
        line = w.get("what_happened") or a.get("summary") or a.get("title") or ""
        y = pdf.get_y()
        pdf.set_font("Helvetica", "B", 8)
        pdf.set_text_color(*_ACCENT)
        pdf.set_xy(pdf.l_margin, y)
        pdf.cell(6, 4, _txt(f"{i:02d}"))
        pdf.set_xy(pdf.l_margin + 6, y)
        pdf.set_font("Helvetica", "", 8.4)
        pdf.set_text_color(*_TEXT)
        pdf.multi_cell(pdf.epw - 6, 4, _txt(line), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(0.8)
    pdf.rule(2.0, 2.0)


def _card(pdf: _Doc, a: Dict, idx: int):
    # Keep a card from splitting immediately after its title.
    if pdf.get_y() > pdf.h - 60:
        pdf.add_page()
    scores = a.get("scores") or {}
    sig = a.get("signal") or ""
    rgb = _SIGNAL_RGB.get(sig.upper(), _MUTED)

    y = pdf.get_y()
    pdf.set_xy(pdf.l_margin, y)
    pdf.tag(sig, rgb, filled=True)
    if a.get("category"):
        pdf.tag(a["category"], _MUTED, filled=False)
    for t in (a.get("status_tags") or [])[:3]:
        pdf.tag(t, _MUTED, filled=False)
    # OVERALL, right-aligned on the tag row
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(*_ACCENT)
    ov = str(scores.get("overall", ""))
    pdf.set_xy(pdf.l_margin + pdf.epw - 22, y - 0.2)
    pdf.cell(22, 4, _txt(f"OVERALL {ov}"), align="R")
    pdf.set_xy(pdf.l_margin, y + 5.2)

    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(*_TEXT)
    pdf.multi_cell(pdf.epw, 4.6, _txt(f"{idx}. {a.get('title') or a.get('link') or ''}"),
                   new_x="LMARGIN", new_y="NEXT")

    meta = a.get("source") or ""
    rel = _rel_time(a.get("timestamp"))
    if rel:
        meta += f"  |  {rel}"
    pdf.set_font("Helvetica", "", 7)
    pdf.set_text_color(*_MUTED)
    pdf.cell(0, 3.6, _txt(meta), new_x="LMARGIN", new_y="NEXT")
    link = a.get("link") or ""
    if link:
        pdf.set_font("Helvetica", "", 6.6)
        pdf.set_text_color(*_ACCENT)
        pdf.multi_cell(pdf.epw, 3.2, _txt(link), new_x="LMARGIN", new_y="NEXT", link=link)
    pdf.ln(1.2)

    w = a.get("writeup") or {}
    wrote = False
    for lbl, key in (("What happened", "what_happened"), ("Why it matters", "why_it_matters"),
                     ("Builder takeaway", "builder_takeaway"), ("No-BS read", "no_bs_read")):
        if w.get(key):
            pdf.label(lbl)
            pdf.para(w[key])
            pdf.ln(0.6)
            wrote = True
    if not wrote and a.get("summary"):
        pdf.para(a["summary"])

    if scores:
        pdf.ln(0.6)
        pdf.label("Signal scores")
        pdf.ln(0.5)
        y0 = pdf.get_y()
        col = pdf.epw / 3.0
        entries = [("Practical", scores.get("practical")), ("Technical", scores.get("technical")),
                   ("Market", scores.get("market")), ("Hype risk", scores.get("hype_risk")),
                   ("Urgency", scores.get("urgency")), ("Overall", scores.get("overall"))]
        for i, (lbl, val) in enumerate(entries):
            r, c = divmod(i, 3)
            pdf.set_xy(pdf.l_margin + c * col, y0 + r * 4.0)
            pdf.score_bar(lbl, val, width=col - 25, emphasize=(lbl == "Overall"))
        pdf.set_y(y0 + 8.4)

    also = [x.get("source", "") for x in (a.get("also_seen_in") or []) if x.get("source")]
    if also:
        pdf.set_font("Helvetica", "I", 6.8)
        pdf.set_text_color(*_MUTED)
        pdf.multi_cell(pdf.epw, 3.4, _txt("also reported by: " + ", ".join(also)),
                       new_x="LMARGIN", new_y="NEXT")
    pdf.rule(2.2, 2.2)


def _more(pdf: _Doc, rest: List[Dict]):
    if not rest:
        return
    if pdf.get_y() > pdf.h - 40:
        pdf.add_page()
    pdf.label(f"More headlines ({len(rest)})")
    pdf.ln(1.0)
    for a in rest:
        if pdf.get_y() > pdf.h - 22:
            pdf.add_page()
        y = pdf.get_y()
        ov = str((a.get("scores") or {}).get("overall", ""))
        pdf.set_font("Helvetica", "B", 7)
        pdf.set_text_color(*_ACCENT)
        pdf.set_xy(pdf.l_margin, y)
        pdf.cell(7, 3.8, _txt(ov))
        pdf.set_font("Helvetica", "", 7.6)
        pdf.set_text_color(*_TEXT)
        title = a.get("title") or a.get("link") or ""
        src = a.get("source") or ""
        pdf.set_xy(pdf.l_margin + 7, y)
        pdf.multi_cell(pdf.epw - 7, 3.8, _txt(f"{title}   [{src}]"),
                       new_x="LMARGIN", new_y="NEXT", link=a.get("link") or "")
        pdf.ln(0.4)


def _skills_section(pdf: _Doc, skills: Dict):
    """Optional 'Skills to acquire' block (weekly run)."""
    if not skills or not skills.get("gaps"):
        return
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 7)
    pdf.set_text_color(*_ACCENT)
    pdf.cell(0, 4, _txt("SKILLS GAP ANALYSIS"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(*_TEXT)
    pdf.cell(0, 7, _txt("Skills to acquire"), new_x="LMARGIN", new_y="NEXT")
    if skills.get("summary"):
        pdf.ln(1)
        pdf.para(skills["summary"], size=8.6, color=_MUTED)
    pdf.rule(2.5, 2.5)
    for i, g in enumerate(skills["gaps"], 1):
        if pdf.get_y() > pdf.h - 45:
            pdf.add_page()
        pri = (g.get("priority") or "").upper()
        rgb = {"HIGH": (194, 65, 12), "MEDIUM": (217, 119, 6)}.get(pri, _MUTED)
        y = pdf.get_y()
        pdf.set_xy(pdf.l_margin, y)
        if pri:
            pdf.tag(pri, rgb, filled=True)
        pdf.set_xy(pdf.l_margin, y + 5.0)
        pdf.set_font("Helvetica", "B", 10.5)
        pdf.set_text_color(*_TEXT)
        pdf.multi_cell(pdf.epw, 4.6, _txt(f"{i}. {g.get('skill') or ''}"),
                       new_x="LMARGIN", new_y="NEXT")
        if g.get("why"):
            pdf.label("Why now")
            pdf.para(g["why"])
        if g.get("keywords"):
            pdf.ln(0.4)
            pdf.label("Learn / search keywords")
            pdf.para(", ".join(g["keywords"]), size=8.4, color=_ACCENT)
        if g.get("evidence"):
            pdf.ln(0.4)
            pdf.label("Seen in")
            pdf.para(g["evidence"], size=7.6, color=_MUTED)
        pdf.rule(2.0, 2.0)
    pdf.set_font("Helvetica", "I", 7.4)
    pdf.set_text_color(*_MUTED)
    pdf.multi_cell(pdf.epw, 3.6, _txt(
        "Mark something learned so it stops appearing:  ./skills.py learned \"<skill>\""),
        new_x="LMARGIN", new_y="NEXT")


def render_pdf(news: Dict, out_path: Path, *, title: str = "AI News Briefing",
               detail_limit: int = 20, skills: Dict | None = None) -> Path:
    """Write the briefing (and optional skills section) to `out_path`."""
    arts = list(news.get("articles") or [])
    pdf = _Doc(title)
    pdf.add_page()
    _header(pdf, news, title)
    if arts:
        _top_signal(pdf, arts[0])
        _what_changed(pdf, arts)
        pdf.label(f"Main updates  |  {min(len(arts), detail_limit)} of {len(arts)}")
        pdf.ln(1.5)
        for i, a in enumerate(arts[:detail_limit], 1):
            _card(pdf, a, i)
        _more(pdf, arts[detail_limit:])
    else:
        pdf.para("No articles matched. Check source availability or widen the time window.",
                 color=_MUTED)
    if skills:
        _skills_section(pdf, skills)
    out_path = Path(out_path)
    pdf.output(str(out_path))
    return out_path


def timestamped_name(prefix: str = "AI_News_Briefing", when: datetime | None = None) -> str:
    when = when or datetime.now()
    return f"{prefix}_{when.strftime('%Y-%m-%d_%H%M')}.pdf"
