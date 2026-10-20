"""Agent session history. The agent writes one of these per run; the renderer copies it into every bundle.

A session is complete only when every SOW page was read and save_scope succeeded after that.
"""


def document(run_id, pages, pages_read, events, messages=None, summary=""):
    return {
        "runId": run_id,
        "phase": "intake",
        "pages": pages,
        "pagesRead": sorted(pages_read),
        "events": list(events),
        "messages": list(messages or []),
        "summary": summary,
    }


def complete(session, page_count, pages=None):
    """True when every page was stored in the trace before a successful save_scope.

    Pass `pages` (the paginated SOW) to require each read event to contain that page's text.
    A stub such as "page 1 of 3" does not count.
    """
    if not isinstance(session, dict) or session.get("status") == "not-recorded":
        return False
    required = list(range(1, page_count + 1))
    if session.get("pages") != page_count or sorted(session.get("pagesRead") or []) != required:
        return False
    seen = set()
    saved = False
    texts = {}
    for ev in session.get("events") or []:
        if not isinstance(ev, dict):
            continue
        if ev.get("tool") == "read_sow_page":
            page = (ev.get("args") or {}).get("page")
            seen.add(page)
            texts[page] = ev.get("result") or ""
        elif ev.get("tool") == "save_scope" and str(ev.get("result", "")).startswith("saved"):
            if seen != set(required):
                return False
            saved = True
    if pages is not None:
        if len(pages) != page_count:
            return False
        for i, page in enumerate(pages, start=1):
            stored = texts.get(i)
            if stored is None or (page and page not in stored):
                return False
    return saved
