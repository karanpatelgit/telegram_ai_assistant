"""
nlp.py - PRODUCTION READY Natural Language Parser
Uses OpenAI GPT-4o-mini (cheaper + more reliable than SambaNova)
"""

import os
import json
import re
import logging
from datetime import datetime
import pytz
import openai

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Timezone
ist = pytz.timezone("Asia/Kolkata")

# OpenAI Client
client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

SYSTEM_PROMPT = """You are a command parser for a Telegram productivity bot.
Parse natural language into exact JSON commands. 

Supported commands:
add_task, today_tasks, done_task, delete_task, add_exam, list_exams, delete_exam, 
add_revision, list_revisions, add_note, list_notes, find_notes, delete_note, 
ask_ai, explain, summarize, decide, study_plan, viral_ideas, caption, 
list_inbox, done_inbox, remember, list_memory, stats, inbox_capture

Rules:
- Return ONLY valid JSON: {"command": "add_task", "args": {...}}
- add_task: infer date/time/category from context
- Use "inbox_capture" for unclear requests
- Date format: YYYY-MM-DD or "today"/"tomorrow"
- Time format: HH:MM or infer 09:00

Examples:
"remind gym tomorrow 7am" → {"command":"add_task","args":{"task":"gym","date":"TOMORROW","time":"07:00","category":"health"}}
"tasks today" → {"command":"today_tasks","args":{}}
"""

def _today_context():
    now = datetime.now(ist)
    return now.strftime("%Y-%m-%d %H:%M")

def _fallback(text):
    return {"command": "inbox_capture", "args": {"text": text}}

def parse_natural_language(user_text):
    print("🚀🚀🚀 NLP FUNCTION CALLED!!!")
    print(f"INPUT: {user_text}")
    print(f"SAMBANOVA_KEY: {bool(os.getenv('SAMBANOVA_API_KEY'))}")
    print(f"OPENAI_KEY: {bool(os.getenv('OPENAI_API_KEY'))}")
    
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_text}
            ],
            max_tokens=200,
            temperature=0.1
        )
        
        raw = response.choices[0].message.content.strip()
        print(f"🔍 RAW RESPONSE: {raw}")
        
        # Extract JSON
        json_match = re.search(r'\{.*\}', raw, re.DOTALL)
        if not json_match:
            print("❌ No JSON found")
            return _fallback(user_text)
        
        parsed = json.loads(json_match.group())
        
        if "command" not in parsed:
            print("❌ No 'command' key")
            return _fallback(user_text)
        
        if "args" not in parsed:
            parsed["args"] = {}
            
        print(f"✅ PARSED: {json.dumps(parsed)}")
        return parsed
        
    except Exception as e:
        print(f"❌ NLP ERROR: {type(e).__name__}: {str(e)}")
        return _fallback(user_text)

# Keep your existing functions
COMMAND_LABELS = {
    "add_task": "Add task", "today_tasks": "Today's tasks", "done_task": "Mark done",
    "delete_task": "Delete task", "add_exam": "Add exam", "list_exams": "List exams",
    "add_revision": "Add revision", "list_revisions": "List revisions",
    "add_note": "Save note", "list_notes": "List notes", "ask_ai": "Ask AI",
    "explain": "Explain", "study_plan": "Study plan", "inbox_capture": "Inbox"
}

def describe_parsed(parsed):
    cmd = parsed.get("command", "unknown")
    args = parsed.get("args", {})
    label = COMMAND_LABELS.get(cmd, cmd.replace("_", " ").title())
    
    if cmd == "add_task":
        return f"{label}: {args.get('task', '')} | {args.get('date', '')} {args.get('time', '')}"
    return label
