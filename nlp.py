        lp_v2.py — ULTIMATE 3-LAYER PARSER ENGINE               ║
║  Layer 1: Lightning keyword detection  (0ms, no deps)            ║
║  Layer 2: Smart NLP extraction         (dateparser + regex)      ║
║  Layer 3: AI fallback                  (Claude → OpenAI → SN)   ║
╚══════════════════════════════════════════════════════════════════╝
 
Usage:
    from lp_v2 import parse_message
    result = await parse_message("remind me to study physics tmr at 6pm")
    # → {"command": "add_task", "args": {"task": "study physics",
    #      "date": "2025-05-16", "time": "18:00", "category": "study"}}
 
Requirements:
    pip install dateparser python-dateutil pytz requests
"""
 
import os
import re
import json
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Optional
 
import pytz
import requests
import dateparser
from dateutil import parser as dateutil_parser
 
logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")
 
# ─── API Keys ────────────────────────────────────────────────────────────────
ANTHROPIC_KEY  = os.getenv("ANTHROPIC_API_KEY")
OPENAI_KEY     = os.getenv("OPENAI_API_KEY")
SAMBANOVA_KEY  = os.getenv("SAMBANOVA_API_KEY")
 
print(f"🔑 Anthropic : {'✅' if ANTHROPIC_KEY  else '❌'}")
print(f"🔑 OpenAI    : {'✅' if OPENAI_KEY     else '❌'}")
print(f"🔑 SambaNova : {'✅' if SAMBANOVA_KEY  else '❌'}")
 
 
# ══════════════════════════════════════════════════════════════════════════════
#  LAYER 1 — KEYWORD TRIE (zero-latency hot-path)
# ══════════════════════════════════════════════════════════════════════════════
 
# Maps (regex pattern, priority) → command
_L1_RULES: list[tuple[re.Pattern, str]] = []
 
def _r(pattern: str, command: str) -> None:
    """Register a Layer-1 rule."""
    _L1_RULES.append((re.compile(pattern, re.I | re.X), command))
 
# ── List commands ─────────────────────────────────────────────────────────────
_r(r'^(show|list|what\s+are|display|get)\s+(my\s+)?tasks?$',            "today_tasks")
_r(r'^tasks?\s*(today|now|list)?$',                                       "today_tasks")
_r(r'what\s+(do\s+i\s+have|should\s+i\s+do)\s+today',                   "today_tasks")
_r(r'^(show|list|my)\s+exams?$',                                          "list_exams")
_r(r'^exams?\s*(list|today|upcoming)?$',                                  "list_exams")
_r(r'^(show|list|my)\s+notes?$',                                          "list_notes")
_r(r'^notes?\s*$',                                                         "list_notes")
_r(r'^(show|list|my)\s+revisions?$',                                      "list_revisions")
_r(r'^revisions?\s*$',                                                     "list_revisions")
_r(r'(stats?|statistics|summary|overview|progress|report)',               "stats")
 
# ── Study plan ────────────────────────────────────────────────────────────────
_r(r'(study\s+plan|study\s+schedule)\s+(for\s+)?\d+\s*(days?|weeks?)',   "study_plan")
 
def _layer1(text: str) -> Optional[dict]:
    """
    Pure regex, sub-millisecond.
    Returns a command dict or None if no confident match.
    """
    t = text.strip()
    for pattern, command in _L1_RULES:
        if pattern.search(t):
            logger.debug("L1 hit → %s", command)
            if command == "today_tasks":
                return {"command": "today_tasks", "args": {}}
            if command == "list_exams":
                return {"command": "list_exams", "args": {}}
            if command == "list_notes":
                return {"command": "list_notes", "args": {}}
            if command == "list_revisions":
                return {"command": "list_revisions", "args": {}}
            if command == "stats":
                return {"command": "stats", "args": {}}
            if command == "study_plan":
                return {"command": "study_plan", "args": {"raw": text}}
    return None
 
 
# ══════════════════════════════════════════════════════════════════════════════
#  LAYER 2 — SMART NLP EXTRACTION (dateparser + intent heuristics)
# ══════════════════════════════════════════════════════════════════════════════
 
# ── Intent signals ────────────────────────────────────────────────────────────
_TASK_SIGNALS = re.compile(
    r'\b(remind(er)?|schedule|add\s+task|task:|set\s+task|do\s+|'
    r'i\s+need\s+to|have\s+to|going\s+to|gonna|will\s+|plan\s+to)\b',
    re.I
)
_EXAM_SIGNALS = re.compile(
    r'\b(exam|test|mock|quiz|viva|paper)\b', re.I
)
_REVISION_SIGNALS = re.compile(
    r'\b(revise?|revision|review|recap|re-read)\b', re.I
)
_NOTE_SIGNALS = re.compile(
    r'\b(note:|notes?:|save\s+note|remember\s+this|memo:|jot)\b', re.I
)
_AI_Q_SIGNALS = re.compile(
    r'^(what\s+is|what\s+are|explain|define|tell\s+me|how\s+(does|do)|why\s+is)\b',
    re.I
)
_DECIDE_SIGNALS = re.compile(
    r'\b(should\s+i|which\s+is\s+better|react\s+or|vs\.?|compare)\b', re.I
)
 
# ── Category keyword maps ─────────────────────────────────────────────────────
_CATEGORIES = {
    "health":  ["gym", "run", "workout", "exercise", "yoga", "walk", "jog",
                 "sleep", "diet", "meditation", "stretch", "swim"],
    "study":   ["study", "exam", "math", "physics", "chemistry", "biology",
                 "read", "learn", "lecture", "assignment", "homework",
                 "practise", "practice", "revision", "revise", "chapter"],
    "work":    ["meeting", "call", "work", "office", "project", "client",
                 "presentation", "deadline", "email", "standup", "sprint"],
    "finance": ["pay", "bill", "bank", "fee", "invoice", "budget", "emi"],
    "social":  ["call", "meet", "party", "dinner", "lunch", "birthday"],
}
 
def _infer_category(text: str) -> str:
    tl = text.lower()
    for cat, words in _CATEGORIES.items():
        if any(w in tl for w in words):
            return cat
    return "general"
 
 
# ── Date extraction via dateparser ────────────────────────────────────────────
_DP_SETTINGS = {
    "PREFER_DATES_FROM": "future",
    "RETURN_AS_TIMEZONE_AWARE": False,
    "PREFER_DAY_OF_MONTH": "first",
    "RELATIVE_BASE": None,          # filled at call time
    "TO_TIMEZONE": "Asia/Kolkata",
}
 
def _extract_datetime(text: str) -> tuple[str, str]:
    """
    Returns (date_str "YYYY-MM-DD", time_str "HH:MM").
    Uses dateparser for robust natural-language understanding:
      tomorrow, next Monday, in 3 days, 16 May, 6pm, 18:30 …
    Falls back to regex for edge cases.
    """
    now = datetime.now(IST).replace(tzinfo=None)
    settings = dict(_DP_SETTINGS, RELATIVE_BASE=now)
 
    parsed = dateparser.parse(text, settings=settings, languages=["en", "hi"])
 
    if parsed:
        date_str = parsed.strftime("%Y-%m-%d")
        time_str = parsed.strftime("%H:%M")
        # If dateparser returned midnight and no explicit time in text, use 09:00
        if time_str == "00:00" and not re.search(
            r'\b(\d{1,2}(:\d{2})?\s*(am|pm)|at\s+\d)', text, re.I
        ):
            time_str = "09:00"
        return date_str, time_str
 
    # ── Regex fallback ────────────────────────────────────────────────────────
    today = now.date()
    date_str = today.strftime("%Y-%m-%d")
    time_str = "09:00"
 
    if re.search(r'\btomorrow\b|\btmr\b', text, re.I):
        date_str = (today + timedelta(days=1)).strftime("%Y-%m-%d")
    elif m := re.search(r'\bin\s+(\d+)\s+(days?|weeks?)\b', text, re.I):
        n = int(m.group(1))
        delta = timedelta(days=n) if "day" in m.group(2) else timedelta(weeks=n)
        date_str = (today + delta).strftime("%Y-%m-%d")
    elif m := re.search(r'\b(next\s+)?(mon|tue|wed|thu|fri|sat|sun)\w*\b', text, re.I):
        day_map = {"mon": 0, "tue": 1, "wed": 2, "thu": 3,
                   "fri": 4, "sat": 5, "sun": 6}
        target_wd = day_map[m.group(0)[:3].lower()]
        days_ahead = (target_wd - today.weekday() + 7) % 7 or 7
        date_str = (today + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
 
    if m := re.search(
        r'(\d{1,2})(?::(\d{2}))?\s*(am|pm)', text, re.I
    ):
        hr = int(m.group(1)); mn = int(m.group(2) or 0)
        suffix = m.group(3).upper()
        if suffix == "PM" and hr != 12: hr += 12
        elif suffix == "AM" and hr == 12: hr = 0
        time_str = f"{hr:02d}:{mn:02d}"
    elif m := re.search(r'\bat\s+(\d{1,2})(?::(\d{2}))?\b', text, re.I):
        hr = int(m.group(1)); mn = int(m.group(2) or 0)
        time_str = f"{hr:02d}:{mn:02d}"
 
    return date_str, time_str
 
 
def _strip_triggers(text: str, patterns: list[str]) -> str:
    """Remove leading trigger words to isolate the content."""
    for p in patterns:
        text = re.sub(p, "", text, flags=re.I).strip(" ,:;-")
    return text or text
 
 
def _parse_task_l2(text: str) -> Optional[dict]:
    if not _TASK_SIGNALS.search(text):
        return None
    task_text = _strip_triggers(text, [
        r'^remind\s+(me\s+)?to\s+',
        r'^add\s+task\s*:?\s*',
        r'^set\s+task\s*:?\s*',
        r'^task\s*:?\s*',
        r'^schedule\s+',
        r'^i\s+need\s+to\s+',
        r'^i\s+have\s+to\s+',
        r'^going\s+to\s+',
        r'^gonna\s+',
        r'^will\s+',
        r'^plan\s+to\s+',
    ])
    # Trim trailing date/time noise from task description
    task_text = re.split(
        r'\b(at|on|by|before|after|tmr|tomorrow|today|next|in\s+\d)\b',
        task_text, maxsplit=1, flags=re.I
    )[0].strip(" ,")
 
    date_str, time_str = _extract_datetime(text)
    return {
        "task": task_text,
        "date": date_str,
        "time": time_str,
        "category": _infer_category(text),
    }
 
 
def _parse_exam_l2(text: str) -> Optional[dict]:
    if not _EXAM_SIGNALS.search(text):
        return None
    # Extract subject — everything before "exam/test"
    m = _EXAM_SIGNALS.search(text)
    subject = text[:m.start()].strip(" ,;:")
    subject = re.sub(r'^(add|new|schedule)\s+', "", subject, flags=re.I).strip()
    date_str, time_str = _extract_datetime(text)
    return {
        "subject": subject.title() or "Unknown",
        "date": date_str,
        "time": time_str,
    }
 
 
def _parse_revision_l2(text: str) -> Optional[dict]:
    if not _REVISION_SIGNALS.search(text):
        return None
    topic = _strip_triggers(text, [
        r'^revise\s+',
        r'^revision\s+(for\s+|on\s+)?',
        r'^review\s+',
        r'^recap\s+(of\s+)?',
    ])
    date_str, time_str = _extract_datetime(text)
    return {"topic": topic.title(), "date": date_str, "time": time_str}
 
 
def _parse_note_l2(text: str) -> Optional[dict]:
    if not _NOTE_SIGNALS.search(text):
        return None
    note = _strip_triggers(text, [
        r'^note\s*:?\s*',
        r'^save\s+note\s*:?\s*',
        r'^remember\s+(this\s+)?:?\s*',
        r'^memo\s*:?\s*',
        r'^jot\s+(down\s+)?:?\s*',
    ])
    return {"note": note}
 
 
def _layer2(text: str) -> Optional[dict]:
    """
    Smart NLP layer — intent classification + entity extraction.
    Returns a command dict or None.
    """
    # AI question → ask_ai
    if _AI_Q_SIGNALS.match(text):
        return {"command": "ask_ai", "args": {"question": text}}
 
    # Decision → ask_ai with decide flag
    if _DECIDE_SIGNALS.search(text):
        return {"command": "ask_ai", "args": {"question": text, "type": "decide"}}
 
    # Note
    if r := _parse_note_l2(text):
        return {"command": "add_note", "args": r}
 
    # Exam (check before task — "add physics exam tmr" is an exam not a task)
    if r := _parse_exam_l2(text):
        return {"command": "add_exam", "args": r}
 
    # Revision
    if r := _parse_revision_l2(text):
        return {"command": "add_revision", "args": r}
 
    # Task
    if r := _parse_task_l2(text):
        return {"command": "add_task", "args": r}
 
    return None
 
 
# ══════════════════════════════════════════════════════════════════════════════
#  LAYER 3 — AI FALLBACK  (Claude → OpenAI → SambaNova)
# ══════════════════════════════════════════════════════════════════════════════
 
_AI_SYSTEM = """You are a precise intent classifier for a student productivity Telegram bot.
 
Parse the user message and respond with ONLY a valid JSON object — no explanation, no markdown fences.
 
Schema:
{
  "command": <one of: add_task | today_tasks | add_exam | list_exams | add_revision |
                       list_revisions | add_note | list_notes | ask_ai | study_plan |
                       stats | inbox_capture>,
  "args": {
    // add_task:     task(str), date(YYYY-MM-DD), time(HH:MM), category(str)
    // add_exam:     subject(str), date(YYYY-MM-DD), time(HH:MM)
    // add_revision: topic(str), date(YYYY-MM-DD), time(HH:MM)
    // add_note:     note(str)
    // ask_ai:       question(str)
    // study_plan:   subjects(str), days(int)
    // inbox_capture: text(str)
    // list/today/stats commands: {} (empty)
  }
}
 
Today's date in IST: {today}
Rules:
- Prefer future dates for relative expressions (tomorrow, next week, etc.)
- Default time 09:00 if none specified
- Default category "general" if none inferable
- Use inbox_capture only if absolutely nothing else fits
"""
 
 
def _ai_parse_claude(text: str) -> Optional[dict]:
    """Call Anthropic Claude with structured JSON output."""
    if not ANTHROPIC_KEY:
        return None
    today = datetime.now(IST).strftime("%Y-%m-%d (%A)")
    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 256,
                "system": _AI_SYSTEM.format(today=today),
                "messages": [{"role": "user", "content": text}],
            },
            timeout=6,
        )
        raw = resp.json()["content"][0]["text"].strip()
        return json.loads(raw)
    except Exception as e:
        logger.warning("Claude parse failed: %s", e)
        return None
 
 
def _ai_parse_openai(text: str) -> Optional[dict]:
    """Call OpenAI with JSON mode."""
    if not OPENAI_KEY:
        return None
    today = datetime.now(IST).strftime("%Y-%m-%d (%A)")
    try:
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENAI_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "gpt-4o-mini",
                "response_format": {"type": "json_object"},
                "max_tokens": 256,
                "messages": [
                    {"role": "system", "content": _AI_SYSTEM.format(today=today)},
                    {"role": "user",   "content": text},
                ],
            },
            timeout=6,
        )
        raw = resp.json()["choices"][0]["message"]["content"]
        return json.loads(raw)
    except Exception as e:
        logger.warning("OpenAI parse failed: %s", e)
        return None
 
 
def _ai_parse_sambanova(text: str) -> Optional[dict]:
    """Call SambaNova with JSON mode."""
    if not SAMBANOVA_KEY:
        return None
    today = datetime.now(IST).strftime("%Y-%m-%d (%A)")
    try:
        resp = requests.post(
            "https://api.sambanova.ai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {SAMBANOVA_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "Meta-Llama-3.1-8B-Instruct",
                "response_format": {"type": "json_object"},
                "max_tokens": 256,
                "messages": [
                    {"role": "system", "content": _AI_SYSTEM.format(today=today)},
                    {"role": "user",   "content": text},
                ],
            },
            timeout=8,
        )
        raw = resp.json()["choices"][0]["message"]["content"]
        return json.loads(raw)
    except Exception as e:
        logger.warning("SambaNova parse failed: %s", e)
        return None
 
 
def _layer3(text: str) -> dict:
    """Try AI providers in order of quality/cost. Always returns a dict."""
    for fn in (_ai_parse_claude, _ai_parse_openai, _ai_parse_sambanova):
        result = fn(text)
        if result and "command" in result:
            logger.info("L3 AI hit via %s → %s", fn.__name__, result["command"])
            return result
    # Ultimate fallback
    return {"command": "inbox_capture", "args": {"text": text}}
 
 
# ══════════════════════════════════════════════════════════════════════════════
#  PUBLIC API
# ══════════════════════════════════════════════════════════════════════════════
 
def parse_message(text: str, use_ai: bool = True) -> dict:
    """
    Main entry point.  Synchronous.
 
    Priority:
      1. Layer 1 — keyword rules       (< 1ms)
      2. Layer 2 — smart NLP           (< 5ms, pure Python + dateparser)
      3. Layer 3 — AI fallback         (network call, only when needed)
 
    Args:
        text:    Raw Telegram message text.
        use_ai:  Set False to disable Layer 3 (testing / offline mode).
 
    Returns:
        {"command": str, "args": dict}
    """
    if not text or not text.strip():
        return {"command": "inbox_capture", "args": {"text": text}}
 
    text = text.strip()
    logger.info("🔍 Parsing: %r", text[:80])
 
    # Layer 1
    if result := _layer1(text):
        logger.info("✅ L1 → %s", result["command"])
        return result
 
    # Layer 2
    if result := _layer2(text):
        logger.info("✅ L2 → %s", result["command"])
        return result
 
    # Layer 3
    if use_ai:
        logger.info("⏳ L3 AI fallback …")
        result = _layer3(text)
        logger.info("✅ L3 → %s", result["command"])
        return result
 
    logger.info("📥 inbox_capture (AI disabled)")
    return {"command": "inbox_capture", "args": {"text": text}}
 
 
async def parse_message_async(text: str, use_ai: bool = True) -> dict:
    """Async wrapper — runs Layer 3 network call in thread pool."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, parse_message, text, use_ai)
 
 
# ── Human-readable summary ────────────────────────────────────────────────────
 
_LABELS = {
    "today_tasks":   "📋 Showing today's tasks",
    "list_exams":    "📚 Listing exams",
    "list_notes":    "📝 Listing notes",
    "list_revisions":"🔁 Listing revisions",
    "stats":         "📊 Showing stats",
    "study_plan":    "🗓 Creating study plan",
    "inbox_capture": "📥 Saved to inbox",
}
 
def describe_parsed(parsed: dict) -> str:
    cmd  = parsed["command"]
    args = parsed.get("args", {})
 
    if cmd == "add_task":
        return (f"✅ Task added: {args.get('task', '?')} "
                f"| {args.get('date','?')} {args.get('time','?')} "
                f"[{args.get('category','general')}]")
    if cmd == "add_exam":
        return f"📝 Exam: {args.get('subject','?')} on {args.get('date','?')} at {args.get('time','?')}"
    if cmd == "add_revision":
        return f"🔁 Revision: {args.get('topic','?')} on {args.get('date','?')}"
    if cmd == "add_note":
        note = args.get("note","")[:60]
        return f"📌 Note saved: {note}…" if len(args.get("note","")) > 60 else f"📌 Note saved: {note}"
    if cmd == "ask_ai":
        return f"🤖 Asking AI: {args.get('question','?')[:60]}"
 
    return _LABELS.get(cmd, cmd.replace("_", " ").title())
 
 
# ══════════════════════════════════════════════════════════════════════════════
#  QUICK SELF-TEST  (python lp_v2.py)
# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
 
    samples = [
        "show my tasks",
        "tasks",
        "list exams",
        "remind me to study physics tomorrow at 6pm",
        "add task: gym session at 7am next Monday",
        "revise organic chemistry on Friday",
        "physics exam next Tuesday at 9am",
        "note: API key format changed to Bearer prefix",
        "what is the photoelectric effect",
        "should I use React or Vue for my project",
        "study plan for 30 days covering maths physics chemistry",
        "I need to call mom tomorrow at 5pm",
        "going to finish the assignment by Thursday night",
        "stats",
        "some random unrecognised gibberish abc xyz",
    ]
 
    print("\n" + "═" * 60)
    print("  PARSE TEST (AI=OFF for speed — set use_ai=True in prod)")
    print("═" * 60)
    for msg in samples:
        result = parse_message(msg, use_ai=False)
        label  = describe_parsed(result)
        print(f"\n  IN : {msg}")
        print(f"  CMD: {result['command']}")
        print(f"  ARG: {result['args']}")
        print(f"  ℹ️  : {label}")
    print("\n" + "═" * 60)
 
