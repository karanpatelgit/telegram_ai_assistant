"""
nlp.py - Natural Language Command Parser
Converts plain-text user messages into structured bot commands using Groq.
"""

import os
import json
import re
import requests
from dotenv import load_dotenv
from datetime import datetime
import pytz

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_URL     = "https://api.groq.com/openai/v1/chat/completions"
HEADERS      = {
    "Authorization": f"Bearer {GROQ_API_KEY}",
    "Content-Type":  "application/json"
}
ist = pytz.timezone("Asia/Kolkata")


# ─── Prompt ──────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a command parser for a personal productivity Telegram bot.
The user will send a plain-English message. Your job is to decide whether it maps
to one of the bot's commands, and if so, return the structured arguments needed.

Today's date (IST): {today}
Current time (IST): {now_time}

## Supported commands and their argument schemas:

| command        | args (JSON keys)                                              |
|----------------|---------------------------------------------------------------|
| add_task       | date (YYYY-MM-DD), task (str), time (HH:MM), category (str)  |
| today_tasks    | (no args)                                                     |
| done_task      | task_id (int)                                                 |
| delete_task    | task_id (int)                                                 |
| add_exam       | subject (str), date (YYYY-MM-DD), time (HH:MM)               |
| list_exams     | (no args)                                                     |
| delete_exam    | exam_id (int)                                                 |
| add_revision   | topic (str), subject (str), days (int, default 3)             |
| list_revisions | (no args)                                                     |
| add_note       | note (str), tags (str, space-separated #hashtags)             |
| list_notes     | (no args)                                                     |
| find_notes     | query (str)                                                   |
| delete_note    | note_id (int)                                                 |
| ask_ai         | question (str)                                                |
| explain        | topic (str)                                                   |
| summarize      | text (str)                                                    |
| decide         | question (str)                                                |
| study_plan     | subjects (str), days (int, default 7)                         |
| viral_ideas    | topic (str)                                                   |
| caption        | topic (str), platform (str, default "instagram")              |
| list_inbox     | (no args)                                                     |
| done_inbox     | inbox_id (int)                                                |
| remember       | key (str), value (str)                                        |
| list_memory    | (no args)                                                     |
| stats          | (no args)                                                     |
| inbox_capture  | text (str)   ← fallback: save as inbox item                   |

## Rules:
- Infer missing date as today unless user says "tomorrow" (+1 day), "day after" (+2), or a weekday name.
- Infer missing time as "09:00" for tasks unless context suggests otherwise.
- Infer category from context: "study"/"exam"/"class" → "study"; "gym"/"workout" → "health"; else "general".
- For ambiguous messages that aren't clearly a command, use "inbox_capture".
- Return ONLY a valid JSON object with keys "command" and "args". No markdown, no explanation.

## Examples:

User: "remind me to submit assignment tomorrow at 5pm"
→ {"command":"add_task","args":{"date":"YYYY-MM-DD+1","task":"Submit assignment","time":"17:00","category":"study"}}

User: "add physics exam on 2025-08-10 at 10am"
→ {"command":"add_exam","args":{"subject":"Physics","date":"2025-08-10","time":"10:00"}}

User: "what are my tasks today"
→ {"command":"today_tasks","args":{}}

User: "note: always drink water before studying #health #habits"
→ {"command":"add_note","args":{"note":"Always drink water before studying","tags":"#health #habits"}}

User: "revise thermodynamics for physics in 4 days"
→ {"command":"add_revision","args":{"topic":"Thermodynamics","subject":"Physics","days":4}}

User: "what is quantum entanglement"
→ {"command":"ask_ai","args":{"question":"What is quantum entanglement?"}}

User: "explain photosynthesis simply"
→ {"command":"explain","args":{"topic":"photosynthesis"}}

User: "should I use React or Vue for my project?"
→ {"command":"decide","args":{"question":"Should I use React or Vue for my project?"}}

User: "ideas for reels on morning routine"
→ {"command":"viral_ideas","args":{"topic":"morning routine"}}

User: "meeting with Rahul tomorrow"
→ {"command":"inbox_capture","args":{"text":"Meeting with Rahul tomorrow"}}
"""


def _today_context() -> dict:
    now = datetime.now(ist)
    return {
        "today":    now.strftime("%Y-%m-%d"),
        "now_time": now.strftime("%H:%M"),
    }


# ─── Core parser ─────────────────────────────────────────────────────────────

def parse_natural_language(user_text: str) -> dict:
    """
    Returns a dict like:
        {"command": "add_task", "args": {"date": "...", "task": "...", ...}}
    or  {"command": "inbox_capture", "args": {"text": "..."}}
    on any failure.
    """
    ctx = _today_context()
    system = SYSTEM_PROMPT.format(**ctx)

    try:
        r = requests.post(
            GROQ_URL,
            headers=HEADERS,
            json={
                "model": "llama-3.1-8b-instant",
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user",   "content": user_text},
                ],
                "max_tokens":  250,
                "temperature": 0.1,   # low temp → deterministic parsing
            },
            timeout=20,
        )
        if r.status_code != 200:
            logging.error(f"Groq error {r.status_code}: {r.text[:300]}")
            return _fallback(user_text)

       raw = r.json()["choices"][0]["message"]["content"].strip()

        # Strip markdown fences more aggressively
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()
        
        # Extract just the JSON object if there's extra text around it
        json_match = re.search(r'\{.*\}', raw, re.DOTALL)
        if not json_match:
            logging.warning(f"No JSON found in Groq response: {raw}")
            return _fallback(text)
        
        raw = json_match.group()
        logging.info(f"Groq extracted JSON: {raw}")
        
        parsed = json.loads(raw)

        # Sanity-check shape
        if "command" not in parsed or "args" not in parsed:
            return _fallback(user_text)

        # Fix relative dates that Groq sometimes returns literally
        parsed = _resolve_relative_dates(parsed, ctx["today"])
        logging.info(f"Groq raw: {raw}")
        logging.info(f"Groq parsed: {parsed}")
        
        return parsed

    except Exception:
        return _fallback(user_text)


def _fallback(text: str) -> dict:
    return {"command": "inbox_capture", "args": {"text": text}}


def _resolve_relative_dates(parsed: dict, today_str: str) -> dict:
    """
    Replace placeholder strings like YYYY-MM-DD+1 with real dates.
    Also resolves weekday names ("monday", "next friday", etc.).
    """
    from datetime import timedelta

    today = datetime.strptime(today_str, "%Y-%m-%d")
    args  = parsed.get("args", {})

    for key in ("date", "exam_date"):
        val = args.get(key, "")
        if not val:
            continue

        # Handle YYYY-MM-DD+N pattern
        m = re.match(r"YYYY-MM-DD\+(\d+)", str(val))
        if m:
            args[key] = (today + timedelta(days=int(m.group(1)))).strftime("%Y-%m-%d")
            continue

        # Handle weekday names
        weekdays = ["monday","tuesday","wednesday","thursday","friday","saturday","sunday"]
        lower = val.lower().replace("next ", "").strip()
        if lower in weekdays:
            target = weekdays.index(lower)
            current = today.weekday()
            delta   = (target - current) % 7 or 7
            args[key] = (today + timedelta(days=delta)).strftime("%Y-%m-%d")
            continue

        # "tomorrow"
        if lower == "tomorrow":
            args[key] = (today + timedelta(days=1)).strftime("%Y-%m-%d")
            continue

        # "today"
        if lower == "today":
            args[key] = today_str

    parsed["args"] = args
    return parsed


# ─── Confidence helper ────────────────────────────────────────────────────────

COMMAND_LABELS = {
    "add_task":       "➕ Add task",
    "today_tasks":    "📋 Today's tasks",
    "done_task":      "✅ Mark task done",
    "delete_task":    "🗑 Delete task",
    "add_exam":       "🎓 Add exam",
    "list_exams":     "📚 List exams",
    "delete_exam":    "🗑 Delete exam",
    "add_revision":   "🧠 Schedule revision",
    "list_revisions": "🗓 List revisions",
    "add_note":       "📝 Save note",
    "list_notes":     "📋 List notes",
    "find_notes":     "🔍 Search notes",
    "delete_note":    "🗑 Delete note",
    "ask_ai":         "🤖 Ask AI",
    "explain":        "💡 Explain topic",
    "summarize":      "📄 Summarize",
    "decide":         "🧭 Decision helper",
    "study_plan":     "📅 Generate study plan",
    "viral_ideas":    "🎬 Viral reel ideas",
    "caption":        "📱 Generate caption",
    "list_inbox":     "📥 View inbox",
    "done_inbox":     "✅ Mark inbox done",
    "remember":       "🧠 Save memory",
    "list_memory":    "🗂 View memory",
    "stats":          "📊 View stats",
    "inbox_capture":  "📥 Save to inbox",
}


def describe_parsed(parsed: dict) -> str:
    """Human-readable summary of what was parsed, for confirmation messages."""
    cmd  = parsed.get("command", "inbox_capture")
    args = parsed.get("args", {})
    label = COMMAND_LABELS.get(cmd, cmd)

    detail_map = {
        "add_task":     lambda a: f"Task: {a.get('task')} | {a.get('date')} {a.get('time')} | [{a.get('category','general')}]",
        "add_exam":     lambda a: f"Subject: {a.get('subject')} | {a.get('date')} {a.get('time')}",
        "add_revision": lambda a: f"Topic: {a.get('topic')} ({a.get('subject')}) in {a.get('days',3)} days",
        "add_note":     lambda a: f"{a.get('note','')[:60]} | Tags: {a.get('tags','none')}",
        "ask_ai":       lambda a: a.get("question","")[:80],
        "explain":      lambda a: a.get("topic","")[:60],
        "decide":       lambda a: a.get("question","")[:80],
        "viral_ideas":  lambda a: a.get("topic","")[:60],
        "caption":      lambda a: f"{a.get('topic','')} on {a.get('platform','instagram')}",
        "study_plan":   lambda a: f"{a.get('subjects','')} for {a.get('days',7)} days",
        "remember":     lambda a: f"{a.get('key')}: {a.get('value')}",
        "find_notes":   lambda a: a.get("query","")[:60],
        "inbox_capture":lambda a: a.get("text","")[:80],
    }

    detail_fn = detail_map.get(cmd)
    detail    = detail_fn(args) if detail_fn else ""
    return f"{label}\n{detail}" if detail else label
