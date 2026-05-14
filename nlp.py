"""
nlp.py - DUAL ENGINE: OpenAI + SambaNova + Keyword Fallback
Tries OpenAI → SambaNova → Keywords → Inbox
"""

import os
import json
import re
import logging
import requests
from datetime import datetime
import pytz

logger = logging.getLogger(__name__)
ist = pytz.timezone("Asia/Kolkata")

# API Configs
OPENAI_KEY = os.getenv("OPENAI_API_KEY")
SAMBANOVA_KEY = os.getenv("SAMBANOVA_API_KEY")

print(f"🔑 OPENAI: {'✅' if OPENAI_KEY else '❌'}")
print(f"🔑 SAMBANOVA: {'✅' if SAMBANOVA_KEY else '❌'}")

SYSTEM_PROMPT = """Parse to JSON command. Output ONLY: {"command":"add_task","args":{}}
Commands: add_task,today_tasks,add_exam,list_exams,add_revision,add_note,ask_ai,study_plan,inbox_capture"""

def _fallback(text):
    return {"command": "inbox_capture", "args": {"text": text}}

def keyword_parser(text):
    text = text.lower()
    
    # BLOCK "show/list" commands from becoming add_task
    if any(word in text for word in ["show ", "list ", "today ", "tasks?"]):
        if "task" in text or "today" in text:
            return {"command": "today_tasks", "args": {}}
        return None  # Let AI handle other lists
    
    # Date/time extraction (your existing code)
    args = {"task": text}
    date_match = re.search(r'(\d{4}-\d{2}-\d{2})|(tomorrow)|(today)', text)
    if date_match:
        args["date"] = date_match.group(1) or "TOMORROW" or "TODAY"
    
    time_match = re.search(r'(\d{1,2})(?::(\d{2}))?\s*(am|pm)', text, re.IGNORECASE)
    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2)) if time_match.group(2) else 0
        if time_match.group(3).upper() == "PM" and hour != 12:
            hour += 12
        args["time"] = f"{hour:02d}:{minute:02d}"
    
    # Smart category
    if any(word in text for word in ["gym", "workout"]):
        args["category"] = "health"
    elif any(word in text for word in ["study", "exam"]):
        args["category"] = "study"
    
    # Only add_task for action words
    if any(word in text for word in ["add task", "remind", "schedule"]):
        return {"command": "add_task", "args": args}
    
    return None
def openai_parser(user_text):
    """OpenAI GPT-4o-mini (fastest/cheapest)"""
    try:
        import openai
        client = openai.OpenAI(api_key=OPENAI_KEY)
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": f"{SYSTEM_PROMPT}\n\n{user_text}"}],
            max_tokens=100,
            temperature=0.1
        )
        
        raw = response.choices[0].message.content.strip()
        json_match = re.search(r'\{.*\}', raw, re.DOTALL)
        if json_match:
            parsed = json.loads(json_match.group())
            if "command" in parsed:
                print("✅ OPENAI SUCCESS")
                return parsed
    except Exception as e:
        print(f"❌ OPENAI: {e}")
    return None

def sambanova_parser(user_text):
    """SambaNova Llama (backup)"""
    try:
        response = requests.post(
            "https://api.sambanova.ai/v1/chat/completions",
            headers={"Authorization": f"Bearer {SAMBANOVA_KEY}", "Content-Type": "application/json"},
            json={
                "model": "meta-llama/Meta-Llama-3.1-8B-Instruct",
                "messages": [{"role": "user", "content": f"{SYSTEM_PROMPT}\n\n{user_text}"}],
                "max_tokens": 100,
                "temperature": 0.1
            },
            timeout=10
        )
        
        if response.status_code == 200:
            raw = response.json()["choices"][0]["message"]["content"].strip()
            json_match = re.search(r'\{.*\}', raw, re.DOTALL)
            if json_match:
                parsed = json.loads(json_match.group())
                if "command" in parsed:
                    print("✅ SAMBANOVA SUCCESS")
                    return parsed
        else:
            print(f"❌ SAMBANOVA {response.status_code}: {response.text[:50]}")
    except Exception as e:
        print(f"❌ SAMBANOVA: {e}")
    return None

def parse_natural_language(user_text):
    """Master parser - tries all engines"""
    print(f"🔍 NLP: {user_text}")
    
    # 1. Keyword (fastest/free)
    result = keyword_parser(user_text)
    if result:
        print("✅ KEYWORD MATCH")
        return result
    
    # 2. OpenAI (best quality)
    if OPENAI_KEY:
        result = openai_parser(user_text)
        if result:
            return result
    
    # 3. SambaNova (backup)
    if SAMBANOVA_KEY:
        result = sambanova_parser(user_text)
        if result:
            return result
    
    # 4. Fallback
    print("📥 FALLBACK: inbox_capture")
    return _fallback(user_text)

# UI Functions (keep existing)
COMMAND_LABELS = {
    "add_task": "Add task", "today_tasks": "Today's tasks", 
    "add_exam": "Add exam", "study_plan": "Study plan",
    "add_revision": "Add revision", "add_note": "Save note",
    "inbox_capture": "📥 Inbox"
}

def describe_parsed(parsed):
    cmd = parsed.get("command", "unknown")
    args = parsed.get("args", {})
    label = COMMAND_LABELS.get(cmd, cmd.replace("_", " ").title())
    
    if cmd == "add_task":
        return f"{label}: {args.get('task', 'Task')}"
    return label
