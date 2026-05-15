"""
lp_v2.py — 3-Layer NLP Parser for Telegram Bot
================================================
Layer 1 : Keyword rules     — instant, no network
Layer 2 : Smart NLP         — dateparser + regex
Layer 3 : AI fallback       — Claude → OpenAI → SambaNova
 
How to use in bot.py:
    from lp_v2 import parse_message_async
    result = await parse_message_async(update.message.text)
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
 
logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")
 
# ──────────────────────────────────────────────
# API KEYS  (set these in your .env file)
# ──────────────────────────────────────────────
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY")
OPENAI_KEY    = os.getenv("OPENAI_API_KEY")
SAMBANOVA_KEY = os.getenv("SAMBANOVA_API_KEY")
 
print(f"🔑 Anthropic : {'✅' if ANTHROPIC_KEY else '❌'}")
print(f"🔑 OpenAI    : {'✅' if OPENAI_KEY    else '❌'}")
print(f"🔑 SambaNova : {'✅' if SAMBANOVA_KEY else '❌'}")
 
 
# ══════════════════════════════════════════════
#  LAYER 1 — KEYWORD RULES  (instant)
# ══════════════════════════════════════════════
 
_L1_RULES = []
 
def _r(pattern, command):
    _L1_RULES.append((re.compile(pattern, re.I), command))
 
_r(r'^(show|list|what are|display|get)\s+(my\s+)?tasks?$',  "today_tasks")
_r(r'^tasks?\s*(today|now|list)?$',                          "today_tasks")
_r(r'what (do i have|should i do) today',                    "today_tasks")
_r(r'^(show|list|my)\s+exams?$',                             "list_exams")
_r(r'^exams?\s*(list|today|upcoming)?$',                     "list_exams")
_r(r'^(show|list|my)\s+notes?$',                             "list_notes")
_r(r'^notes?\s*$',                                           "list_notes")
_r(r'^(show|list|my)\s+revisions?$',                         "list_revisions")
_r(r'^revisions?\s*$',                                       "list_revisions")
_r(r'\b(stats?|statistics|summary|overview|progress)\b',     "stats")
_r(r'(study plan|study schedule).+\d+\s*(days?|weeks?)',     "study_plan")
 
 
def _layer1(text):
    for pattern, command in _L1_RULES:
        if pattern.search(text.strip()):
            if command == "study_plan":
                return {"command": "study_plan", "args": {"raw": text}}
            return {"command": command, "args": {}}
    return None
 
 
# ══════════════════════════════════════════════
#  LAYER 2 — SMART NLP  (dateparser + regex)
# ══════════════════════════════════════════════
 
# Intent signals
_TASK_SIGNALS = re.compile(
    r'\b(remind(er)?|schedule|add task|task:|set task|'
    r'i need to|have to|going to|gonna|plan to)\b', re.I)
 
_EXAM_SIGNALS     = re.compile(r'\b(exam|test|mock|quiz|viva|paper)\b', re.I)
_REVISION_SIGNALS = re.compile(r'\b(revise?|revision|review|recap)\b', re.I)
_NOTE_SIGNALS     = re.compile(r'\b(note:|notes?:|save note|remember this|memo:|jot)\b', re.I)
_AI_Q_SIGNALS     = re.compile(r'^(what is|what are|explain|define|tell me|how does|how do|why is)\b', re.I)
_DECIDE_SIGNALS   = re.compile(r'\b(should i|which is better|vs\.?|compare)\b', re.I)
 
# Categories
_CATEGORIES = {
    "health":  ["gym", "run", "workout", "exercise", "yoga", "walk",
                 "jog", "sleep", "diet", "meditation", "swim"],
    "study":   ["study", "exam", "math", "physics", "chemistry", "biology",
                 "read", "learn", "lecture", "assignment", "homework",
                 "revision", "revise", "chapter", "practise"],
    "work":    ["meeting", "call", "work", "office", "project", "client",
                 "presentation", "deadline", "email", "standup"],
    "finance": ["pay", "bill", "bank", "fee", "invoice", "budget", "emi"],
    "social":  ["party", "dinner", "lunch", "birthday", "meet"],
}
 
def _infer_category(text):
    tl = text.lower()
    for cat, words in _CATEGORIES.items():
        if any(w in tl for w in words):
            return cat
    return "general"
 
 
def _extract_datetime(text):
    """
    Returns (date_str, time_str) e.g. ("2025-05-16", "18:00")
    Uses dateparser first, then falls back to simple regex.
    """
    now = datetime.now(IST).replace(tzinfo=None)
    settings = {
        "PREFER_DATES_FROM": "future",
        "RETURN_AS_TIMEZONE_AWARE": False,
        "PREFER_DAY_OF_MONTH": "first",
        "RELATIVE_BASE": now,
        "TO_TIMEZONE": "Asia/Kolkata",
    }
 
    parsed = dateparser.parse(text, settings=settings, languages=["en", "hi"])
 
    if parsed:
        date_str = parsed.strftime("%Y-%m-%d")
        time_str = parsed.strftime("%H:%M")
        # If no explicit time was given, default to 09:00
        if time_str == "00:00" and not re.search(
            r'\b(\d{1,2}(:\d{2})?\s*(am|pm)|at\s+\d)', text, re.I
        ):
            time_str = "09:00"
        return date_str, time_str
 
    # ── Regex fallback ──────────────────────────
    today    = now.date()
    date_str = today.strftime("%Y-%m-%d")
    time_str = "09:00"
 
    if re.search(r'\b(tomorrow|tmr)\b', text, re.I):
        date_str = (today + timedelta(days=1)).strftime("%Y-%m-%d")
    else:
        m = re.search(r'\bin (\d+) (days?|weeks?)\b', text, re.I)
        if m:
            n     = int(m.group(1))
            delta = timedelta(days=n) if "day" in m.group(2) else timedelta(weeks=n)
            date_str = (today + delta).strftime("%Y-%m-%d")
        else:
            m = re.search(r'\b(next\s+)?(mon|tue|wed|thu|fri|sat|sun)\w*\b', text, re.I)
            if m:
                day_map = {"mon": 0, "tue": 1, "wed": 2, "thu": 3,
                           "fri": 4, "sat": 5, "sun": 6}
                wd         = day_map[m.group(0)[:3].lower()]
                days_ahead = (wd - today.weekday() + 7) % 7 or 7
                date_str   = (today + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
 
    m = re.search(r'(\d{1,2})(?::(\d{2}))?\s*(am|pm)', text, re.I)
    if m:
        hr = int(m.group(1))
        mn = int(m.group(2) or 0)
        if m.group(3).upper() == "PM" and hr != 12:
            hr += 12
        elif m.group(3).upper() == "AM" and hr == 12:
            hr = 0
        time_str = f"{hr:02d}:{mn:02d}"
    else:
        m = re.search(r'\bat (\d{1,2})(?::(\d{2}))?\b', text, re.I)
        if m:
            hr       = int(m.group(1))
            mn       = int(m.group(2) or 0)
            time_str = f"{hr:02d}:{mn:02d}"
 
    return date_str, time_str
 
 
def _strip_triggers(text, patterns):
    """Remove trigger words from the start of text."""
    for p in patterns:
        text = re.sub(p, "", text, flags=re.I).strip(" ,:;-")
    return text
 
 
def _parse_task_l2(text):
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
        r'^plan\s+to\s+',
    ])
    # Cut off date/time tail from task description
    parts = re.split(
        r'\b(at|on|by|tmr|tomorrow|today|next|in \d)\b',
        task_text, maxsplit=1, flags=re.I
    )
    task_text = parts[0].strip(" ,")
 
    date_str, time_str = _extract_datetime(text)
    return {
        "task":     task_text,
        "date":     date_str,
        "time":     time_str,
        "category": _infer_category(text),
    }
 
 
def _parse_exam_l2(text):
    if not _EXAM_SIGNALS.search(text):
        return None
    m       = _EXAM_SIGNALS.search(text)
    subject = text[:m.start()].strip(" ,;:")
    subject = re.sub(r'^(add|new|schedule)\s+', "", subject, flags=re.I).strip()
    date_str, time_str = _extract_datetime(text)
    return {
        "subject": subject.title() or "Unknown",
        "date":    date_str,
        "time":    time_str,
    }
 
 
def _parse_revision_l2(text):
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
 
 
def _parse_note_l2(text):
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
 
 
def _layer2(text):
    if _AI_Q_SIGNALS.match(text):
        return {"command": "ask_ai", "args": {"question": text}}
    if _DECIDE_SIGNALS.search(text):
        return {"command": "ask_ai", "args": {"question": text, "type": "decide"}}
 
    r = _parse_note_l2(text)
    if r:
        return {"command": "add_note", "args": r}
 
    r = _parse_exam_l2(text)
    if r:
        return {"command": "add_exam", "args": r}
 
    r = _parse_revision_l2(text)
    if r:
        return {"command": "add_revision", "args": r}
 
    r = _parse_task_l2(text)
    if r:
        return {"command": "add_task", "args": r}
 
    return None
 
 
# ══════════════════════════════════════════════
#  LAYER 3 — AI FALLBACK
#  Tries: Claude → OpenAI → SambaNova
# ══════════════════════════════════════════════
 
_AI_SYSTEM = """You are a precise intent classifier for a student productivity Telegram bot.
 
Parse the user message and respond with ONLY a valid JSON object.
No explanation. No markdown fences. Just raw JSON.
 
Commands: add_task, today_tasks, add_exam, list_exams, add_revision,
          list_revisions, add_note, list_notes, ask_ai, study_plan,
          stats, inbox_capture
 
Output format:
{{
  "command": "<command>",
  "args": {{
    "task":     "...",
    "date":     "YYYY-MM-DD",
    "time":     "HH:MM",
    "category": "study|health|work|finance|social|general",
    "subject":  "...",
    "topic":    "...",
    "note":     "...",
    "question": "...",
    "text":     "..."
  }}
}}
 
Today (IST): {today}
Rules:
- Always prefer future dates
- Default time 09:00 if not mentioned
- Use inbox_capture only if nothing fits
"""
 
 
def _ai_parse_claude(text):
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
        logger.warning("Claude failed: %s", e)
        return None
 
 
def _ai_parse_openai(text):
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
        logger.warning("OpenAI failed: %s", e)
        return None
 
 
def _ai_parse_sambanova(text):
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
        logger.warning("SambaNova failed: %s", e)
        return None
 
 
def _layer3(text):
    for fn in (_ai_parse_claude, _ai_parse_openai, _ai_parse_sambanova):
        result = fn(text)
        if result and "command" in result:
            logger.info("L3 hit via %s → %s", fn.__name__, result["command"])
            return result
    return {"command": "inbox_capture", "args": {"text": text}}
 
 
# ══════════════════════════════════════════════
#  PUBLIC FUNCTIONS  ← import these in bot.py
# ══════════════════════════════════════════════
 
def parse_message(text: str, use_ai: bool = True) -> dict:
    """
    Synchronous parser.
    Returns: {"command": "...", "args": {...}}
    """
    if not text or not text.strip():
        return {"command": "inbox_capture", "args": {"text": text}}
 
    text = text.strip()
    logger.info("Parsing: %r", text[:80])
 
    result = _layer1(text)
    if result:
        logger.info("L1 → %s", result["command"])
        return result
 
    result = _layer2(text)
    if result:
        logger.info("L2 → %s", result["command"])
        return result
 
    if use_ai:
        result = _layer3(text)
        logger.info("L3 → %s", result["command"])
        return result
 
    return {"command": "inbox_capture", "args": {"text": text}}
 
 
async def parse_message_async(text: str, use_ai: bool = True) -> dict:
    """
    Async version — use this in your Telegram bot handlers.
 
    Example:
        from lp_v2 import parse_message_async
 
        async def handle(update, context):
            result = await parse_message_async(update.message.text)
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, parse_message, text, use_ai)
 
 
def describe_parsed(parsed: dict) -> str:
    """Returns a human-readable summary string."""
    cmd  = parsed["command"]
    args = parsed.get("args", {})
 
    if cmd == "add_task":
        return (f"✅ Task: {args.get('task','?')} | "
                f"{args.get('date','?')} {args.get('time','?')} "
                f"[{args.get('category','general')}]")
    if cmd == "add_exam":
        return f"📝 Exam: {args.get('subject','?')} on {args.get('date','?')} at {args.get('time','?')}"
    if cmd == "add_revision":
        return f"🔁 Revision: {args.get('topic','?')} on {args.get('date','?')}"
    if cmd == "add_note":
        note = args.get("note", "")
        return f"📌 Note: {note[:60]}{'…' if len(note) > 60 else ''}"
    if cmd == "ask_ai":
        return f"🤖 AI: {args.get('question','?')[:60]}"
 
    labels = {
        "today_tasks":    "📋 Showing today's tasks",
        "list_exams":     "📚 Listing exams",
        "list_notes":     "📝 Listing notes",
        "list_revisions": "🔁 Listing revisions",
        "stats":          "📊 Showing stats",
        "study_plan":     "🗓 Creating study plan",
        "inbox_capture":  "📥 Saved to inbox",
    }
    return labels.get(cmd, cmd.replace("_", " ").title())
 
 
# ══════════════════════════════════════════════
#  SELF TEST — run:  python lp_v2.py
# ══════════════════════════════════════════════
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
 
    tests = [
        "show my tasks",
        "tasks",
        "list exams",
        "exams",
        "stats",
        "remind me to study physics tomorrow at 6pm",
        "add task: gym at 7am next Monday",
        "I need to call mom tomorrow at 5pm",
        "going to finish assignment by Thursday night",
        "physics exam next Tuesday at 9am",
        "revise organic chemistry on Friday",
        "note: remember to submit fees by Monday",
        "what is the photoelectric effect",
        "should I use React or Vue",
        "study plan for 30 days covering maths physics chemistry",
        "random gibberish xyz abc 123",
    ]
 
    print("\n" + "=" * 55)
    print("  SELF TEST  (AI disabled — set use_ai=True in prod)")
    print("=" * 55)
    for msg in tests:
        result = parse_message(msg, use_ai=False)
        print(f"\n  IN  : {msg}")
        print(f"  CMD : {result['command']}")
        print(f"  ARGS: {result['args']}")
        print(f"  INFO: {describe_parsed(result)}")
    print("\n" + "=" * 55)
