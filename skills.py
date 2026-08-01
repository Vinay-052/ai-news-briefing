#!/usr/bin/env python3
"""Manage the skills gap: see it, and mark things off as you learn them.

    ./skills.py                          # overview: CV skills, learned, current gaps
    ./skills.py gaps                     # re-run the analysis over recent news
    ./skills.py gaps --days 14 --send    # ...over 14 days, and email the result
    ./skills.py learned "vLLM"           # mark learned -> stops being suggested
    ./skills.py unlearn "vLLM"           # undo that
    ./skills.py dismiss "Mojo"           # never suggest this one
    ./skills.py undismiss "Mojo"
    ./skills.py cv                       # show the skills read from your CV
    ./skills.py refresh-cv               # re-read the CV (after you update it)

Run through the venv (or via ./run.sh style paths):
    ./venv/bin/python skills.py ...
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

try:
    import httpx  # noqa: F401  (imported for the shared llm client)
except ImportError as e:
    sys.stderr.write(
        f"\nMissing dependency: {e.name}\n\n"
        f"Use the project venv:\n    {HERE}/venv/bin/python skills.py {' '.join(sys.argv[1:])}\n\n")
    sys.exit(2)

import skills_gap as sg
from config import CONFIG


# ------------------------------------------------------------------ llm bridge
async def _with_llm(coro_factory):
    """Run `coro_factory(llm)` with a shared HTTP client + llm callable."""
    import httpx as _httpx
    from brief import llm_call

    async with _httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        async def llm(prompt: str, max_tokens: int = 2048) -> str:
            return await llm_call(client, prompt, max_tokens=max_tokens)
        return await coro_factory(llm)


def _require_llm() -> bool:
    if not (CONFIG.LLM_BASE_URL and CONFIG.LLM_MODEL) or (
            CONFIG.PROVIDER == "openai" and not CONFIG.LLM_API_KEY):
        print("!! LLM not configured. Run:  ./configure.py --llm")
        return False
    return True


def _cv_path() -> Path:
    p = Path(CONFIG.CV_PATH) if CONFIG.CV_PATH else (HERE / "cv.pdf")
    return p if p.is_absolute() else (HERE / p)


# ------------------------------------------------------------------ display
def _print_gaps(report: dict):
    gaps = report.get("gaps") or []
    if not gaps:
        print("  (no gaps recorded — run: ./skills.py gaps)")
        return
    if report.get("summary"):
        print(f"\n  {report['summary']}\n")
    for i, g in enumerate(gaps, 1):
        pri = (g.get("priority") or "medium").upper()
        print(f"  {i}. [{pri}] {g.get('skill')}")
        if g.get("why"):
            print(f"       why: {g['why']}")
        if g.get("keywords"):
            print(f"       learn: {', '.join(g['keywords'])}")
        if g.get("evidence"):
            print(f"       seen in: {g['evidence']}")
        print()


def cmd_show(state: dict):
    cv = state.get("cv_skills") or []
    learned = state.get("learned") or []
    dismissed = state.get("dismissed") or []
    rep = state.get("last_analysis") or {}
    print(f"CV skills on file : {len(cv)}"
          + (f"   (read {state.get('cv_extracted_at','?')})" if cv else "   — run ./skills.py refresh-cv"))
    print(f"Marked learned    : {len(learned)}")
    for e in learned[-12:]:
        print(f"    + {e.get('skill')}  ({e.get('date','')})")
    if len(learned) > 12:
        print(f"    … and {len(learned)-12} more")
    if dismissed:
        print(f"Dismissed         : {', '.join(dismissed)}")
    print(f"\nLast analysis     : {rep.get('generated_at','never')}"
          + (f"   ({rep.get('articles_considered',0)} items reviewed)" if rep else ""))
    _print_gaps(rep)


# ------------------------------------------------------------------ commands
def cmd_gaps(state: dict, days: int, send: bool) -> int:
    if not _require_llm():
        return 2
    articles = sg.load_history(days)
    if not articles:
        print(f"No news history in the last {days} days.\n"
              "History is written by each briefing run — try ./run.sh --dry-run first.")
        return 1

    async def work(llm):
        try:
            await sg.ensure_cv_skills(state, _cv_path(), llm, log=lambda m: print(f"  {m}"))
        except (FileNotFoundError, ValueError) as e:
            print(f"!! CV: {e}")
            print(f"   Point at it with: ./configure.py --set CV_PATH=/path/to/cv.pdf")
            return None
        return await sg.analyze(state, articles, llm,
                                max_gaps=CONFIG.MAX_SKILL_GAPS, log=lambda m: print(f"  {m}"))

    report = asyncio.run(_with_llm(work))
    if report is None:
        return 2
    sg.save_state(state)
    print(f"\nSkills to acquire  ({report.get('articles_considered',0)} items reviewed, "
          f"{report.get('skills_known',0)} skills on file)")
    _print_gaps(report)

    if send:
        from render import render_news_html
        from brief import send_email
        from datetime import datetime
        html = render_news_html({"articles": [], "input_sources": [], "errors": []},
                                title="Skills to acquire", skills=report)
        send_email(html, f"AI Skills Gap — {datetime.now():%b %d, %Y}")
        print(f"Emailed to {CONFIG.MAIL_TO}")
    return 0


def cmd_cv(state: dict, refresh: bool) -> int:
    if refresh:
        if not _require_llm():
            return 2

        async def work(llm):
            return await sg.ensure_cv_skills(state, _cv_path(), llm, force=True,
                                             log=lambda m: print(f"  {m}"))
        try:
            asyncio.run(_with_llm(work))
        except (FileNotFoundError, ValueError) as e:
            print(f"!! {e}")
            return 2
        sg.save_state(state)
        print("CV skills refreshed.\n")
    skills = state.get("cv_skills") or []
    if not skills:
        print("No CV skills on file yet — run: ./skills.py refresh-cv")
        return 1
    print(f"{len(skills)} skills read from {_cv_path().name}:\n")
    for s in skills:
        print(f"  - {s}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Track the AI skills gap between your CV and the news.")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("show", help="overview (default)")
    sub.add_parser("list", help="alias for show")
    g = sub.add_parser("gaps", help="re-run the gap analysis over recent news")
    g.add_argument("--days", type=int, default=None, help="days of history to consider")
    g.add_argument("--send", action="store_true", help="also email the result")
    for name, helptext in (("learned", "mark a skill as learned"),
                           ("unlearn", "undo 'learned'"),
                           ("dismiss", "never suggest this skill"),
                           ("undismiss", "undo 'dismiss'")):
        s = sub.add_parser(name, help=helptext)
        s.add_argument("skill", nargs="+", help="skill name (quote it)")
    sub.add_parser("cv", help="show skills read from the CV")
    sub.add_parser("refresh-cv", help="re-read the CV PDF")
    a = p.parse_args()

    state = sg.load_state()
    cmd = a.cmd or "show"

    if cmd in ("show", "list"):
        cmd_show(state)
        return 0
    if cmd == "gaps":
        return cmd_gaps(state, a.days or CONFIG.SKILLS_WINDOW_DAYS, a.send)
    if cmd == "cv":
        return cmd_cv(state, refresh=False)
    if cmd == "refresh-cv":
        return cmd_cv(state, refresh=True)

    skill = " ".join(a.skill).strip()
    if cmd == "learned":
        ok = sg.mark_learned(state, skill)
        print(f"{'Marked learned' if ok else 'Already marked'}: {skill}")
    elif cmd == "unlearn":
        ok = sg.unmark_learned(state, skill)
        print(f"{'Removed from learned' if ok else 'Was not in learned'}: {skill}")
    elif cmd == "dismiss":
        ok = sg.dismiss(state, skill)
        print(f"{'Dismissed' if ok else 'Already dismissed'}: {skill}")
    elif cmd == "undismiss":
        ok = sg.undismiss(state, skill)
        print(f"{'Un-dismissed' if ok else 'Was not dismissed'}: {skill}")
    sg.save_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
