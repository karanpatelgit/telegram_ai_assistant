import os
from openai import AsyncOpenAI
import asyncio
import logging
from datetime import datetime, time as dtime
 
import pytz
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import Conflict
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ContextTypes, filters, CallbackQueryHandler
)
 
from database import (
    add_task, get_tasks, complete_task, delete_task,
    add_exam, get_exams, delete_exam,
    add_note, get_notes, search_notes, delete_note,
    add_revision, get_all_revisions,
    add_content, get_content,
    add_inbox, get_inbox, process_inbox_item,
    set_memory, get_memory, get_all_memory,
    get_analytics_summary, log_analytics, get_conn
)
from ai import (
    ask_anything, explain_simple, summarize_text,
    decision_helper, viral_ideas, generate_caption,
    study_plan, motivation_line, chat_with_history
)
from scheduler import (
    check_tasks, check_revisions, check_exam_countdown,
    morning_briefing, night_summary
)
from lp_v2 import parse_message_async
from tg_utils import send_long, edit_long   # ← message splitter
 
load_dotenv()
TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
ist     = pytz.timezone("Asia/Kolkata")
 
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
 
conversation_history = {}
 
# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
 
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    if isinstance(context.error, Conflict):
        logging.warning("⚠️ Conflict: old instance still alive, waiting...")
        await asyncio.sleep(5)
    else:
        logging.error(f"Error: {context.error}")
 
async def post_init(application: Application):
    await application.bot.delete_webhook(drop_pending_updates=True)
    await asyncio.sleep(5)
    logging.info("✅ Bot initialized")
 
 
# ─────────────────────────────────────────────────────────────────────────────
# /start & menus
# ─────────────────────────────────────────────────────────────────────────────
 
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton("📋 Tasks",    callback_data="menu_tasks"),
            InlineKeyboardButton("🎓 Study",    callback_data="menu_study"),
        ],
        [
            InlineKeyboardButton("📝 Notes",    callback_data="menu_notes"),
            InlineKeyboardButton("🧠 Revision", callback_data="menu_revision"),
        ],
        [
            InlineKeyboardButton("🎬 Content",  callback_data="menu_content"),
            InlineKeyboardButton("📥 Inbox",    callback_data="menu_inbox"),
        ],
        [
            InlineKeyboardButton("🤖 AI Tools", callback_data="menu_ai"),
            InlineKeyboardButton("🧠 Memory",   callback_data="menu_memory"),
        ],
        [InlineKeyboardButton("📊 Stats", callback_data="menu_stats")],
    ]
    await update.message.reply_text(
        "🤖 <b>AI Life OS Bot</b>\n\n"
        "You can use /commands <b>or just type naturally!</b>\n\n"
        "Examples:\n"
        "• <i>Add gym tomorrow at 7am</i>\n"
        "• <i>What are my tasks today?</i>\n"
        "• <i>Note: drink 3L water daily</i>\n"
        "• <i>Revise Newton's laws in 3 days</i>\n\n"
        "Choose a category below, or just start typing 👇",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )
 
async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data  = query.data
 
    # ── Use HTML parse mode — avoids Markdown breaking on / _ * chars ──────
    menus = {
        "menu_tasks": (
            "📋 <b>Tasks</b>\n\n"
            "/add YYYY-MM-DD, task, HH:MM, category\n"
            "/today — today's tasks\n"
            "/done ID — mark done\n"
            "/deltask ID — delete task\n\n"
            "<i>Or just type: 'Add submit report tomorrow at 3pm'</i>"
        ),
        "menu_study": (
            "🎓 <b>Study</b>\n\n"
            "/addexam subject YYYY-MM-DD HH:MM\n"
            "/exams — list all exams\n"
            "/delexam ID — delete exam\n"
            "/studyplan subjects, days\n\n"
            "<i>Or: 'Add physics exam on Aug 10 at 10am'</i>"
        ),
        "menu_notes": (
            "📝 <b>Notes</b>\n\n"
            "/note text #tag — save a note\n"
            "/notes — list all notes\n"
            "/find keyword — search notes\n"
            "/delnote ID — delete note\n\n"
            "<i>Or: 'Note: always review before sleeping #habit'</i>"
        ),
        "menu_revision": (
            "🧠 <b>Revision</b>\n\n"
            "/revise topic, subject, days\n"
            "/revisions — view schedule\n\n"
            "Uses spaced repetition. Reminders auto-sent!\n\n"
            "<i>Or: 'Revise thermodynamics for Physics in 4 days'</i>"
        ),
        "menu_content": (
            "🎬 <b>Content Creator</b>\n\n"
            "/idea topic — 5 viral reel ideas\n"
            "/caption topic, platform\n"
            "/savecontent type, content, platform\n"
            "/content — view idea bank"
        ),
        "menu_inbox": (
            "📥 <b>Inbox</b>\n\n"
            "Send any text → saved to inbox.\n"
            "/inbox — view all items\n"
            "/done_inbox ID — mark processed"
        ),
        "menu_ai": (
            "🤖 <b>AI Tools</b>\n\n"
            "/ask question — chat with AI\n"
            "/chat message — casual chat with AI\n"
            "/reset — reset conversation\n"
            "/clear — clear chat history\n"
            "/explain topic — simple explanation\n"
            "/summarize text — summarize\n"
            "/decide question — decision helper\n"
            "/generate prompt — create an AI image\n\n"
            "<i>Or just ask anything in plain English!</i>"
        ),
        "menu_memory": (
            "🧠 <b>Memory</b>\n\n"
            "/remember key: value\n"
            "/memory — view all memories\n\n"
            "<i>Or: 'Remember my college: IIT Delhi'</i>"
        ),
        "menu_stats": (
            "📊 <b>Analytics</b>\n\n"
            "/stats — view usage stats\n"
            "/start — open the main command menu"
        ),
    }
 
    # ── Shared keyboard builder ─────────────────────────────────────────────
    def main_keyboard():
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📋 Tasks",    callback_data="menu_tasks"),
                InlineKeyboardButton("🎓 Study",    callback_data="menu_study"),
            ],
            [
                InlineKeyboardButton("📝 Notes",    callback_data="menu_notes"),
                InlineKeyboardButton("🧠 Revision", callback_data="menu_revision"),
            ],
            [
                InlineKeyboardButton("🎬 Content",  callback_data="menu_content"),
                InlineKeyboardButton("📥 Inbox",    callback_data="menu_inbox"),
            ],
            [
                InlineKeyboardButton("🤖 AI Tools", callback_data="menu_ai"),
                InlineKeyboardButton("🧠 Memory",   callback_data="menu_memory"),
            ],
            [InlineKeyboardButton("📊 Stats",       callback_data="menu_stats")],
        ])
 
    back_markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton("⬅️ Back to Menu", callback_data="menu_main")]]
    )
 
    try:
        if data == "menu_main":
            await query.edit_message_text(
                "🤖 <b>AI Life OS Bot</b>\n\nChoose a category:",
                reply_markup=main_keyboard(),
                parse_mode="HTML"
            )
        elif data in menus:
            await query.edit_message_text(
                menus[data],
                reply_markup=back_markup,
                parse_mode="HTML"
            )
        else:
            # Unknown callback — just refresh main menu
            await query.edit_message_text(
                "🤖 <b>AI Life OS Bot</b>\n\nChoose a category:",
                reply_markup=main_keyboard(),
                parse_mode="HTML"
            )
    except Exception as e:
        logging.warning(f"Menu callback error ({data}): {e}")
        # If edit fails (e.g. message too old), send a fresh menu
        await query.message.reply_text(
            "🤖 <b>AI Life OS Bot</b>\n\nChoose a category:",
            reply_markup=main_keyboard(),
            parse_mode="HTML"
        )
 #---------------------Ai utility-------------------------------------------
 
openai_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
 
 
async def generate_ai_image(prompt: str) -> str:
    try:
        response = await openai_client.images.generate(
            model="dall-e-3",  # or dall-e-2 for cheaper testing
            prompt=prompt,
            n=1,
            size="1024x1024"
        )
        # Returns the URL of the generated image
        return response.data[0].url
    except Exception as e:
        print(f"Image Gen Error: {e}")
        return None


async def cmd_generate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Extract the prompt from /generate arguments
    if not context.args:
        await update.message.reply_text("❌ Please provide a prompt. Example: /generate a futuristic city")
        return
    
    prompt = " ".join(context.args)
    
    # Send a placeholder loading message
    loading_msg = await update.message.reply_text("🎨 Generating your image, please wait...")
    
    image_url = await generate_ai_image(prompt)
    
    if image_url:
        # Send the photo using the URL and delete the loading message
        await update.message.reply_photo(photo=image_url, caption=f"✨ Here is your image for: _{prompt}_")
        await loading_msg.delete()
    else:
        await loading_msg.edit_text("❌ Failed to generate image. Please try a different prompt or check your API quota.")
# ─────────────────────────────────────────────────────────────────────────────
# Slash commands
# ─────────────────────────────────────────────────────────────────────────────
 
async def cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text  = update.message.text.replace("/add", "").strip()
        parts = [p.strip() for p in text.split(",")]
        date, task, time = parts[0], parts[1], parts[2]
        category = parts[3] if len(parts) > 3 else "general"
        add_task(date, task, time, category)
        log_analytics("task_added")
        await update.message.reply_text(
            f"✅ Task added!\n📅 {date} | {time}\n📝 {task}\n🏷 {category}"
        )
    except:
        await update.message.reply_text("Usage:\n/add YYYY-MM-DD, Task, HH:MM, category")
 
async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = datetime.now(ist).strftime("%Y-%m-%d")
    tasks = get_tasks(date=today)
    if not tasks:
        await update.message.reply_text("No tasks today!")
        return
    msg = f"📅 Tasks for {today}\n\n"
    for t in tasks:
        icon = "✅" if t[4] == "Done" else "⏳"
        msg += f"{icon} [{t[0]}] {t[3]} - {t[2]} ({t[5]})\n"
    await send_long(update.message, msg)
 
async def cmd_done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        task_id = int(update.message.text.replace("/done", "").strip())
        complete_task(task_id)
        await update.message.reply_text("✅ Marked as done!")
    except:
        await update.message.reply_text("Usage: /done ID")
 
async def cmd_deltask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        task_id = int(update.message.text.replace("/deltask", "").strip())
        delete_task(task_id)
        await update.message.reply_text("🗑 Task deleted")
    except:
        await update.message.reply_text("Usage: /deltask ID")
 
async def cmd_addexam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text = update.message.text.replace("/addexam", "").strip()
        parts = text.split()
        subject, exam_date, exam_time = parts[0], parts[1], parts[2]
        add_exam(subject, exam_date, exam_time)
        log_analytics("exam_added")
        delta = (datetime.strptime(exam_date, "%Y-%m-%d") - datetime.now()).days
        await update.message.reply_text(
            f"🎓 Exam added!\n📚 {subject}\n📅 {exam_date} at {exam_time}\n⏳ {delta} days remaining"
        )
    except:
        await update.message.reply_text("Usage: /addexam subject YYYY-MM-DD HH:MM")
 
async def cmd_exams(update: Update, context: ContextTypes.DEFAULT_TYPE):
    exams = get_exams()
    if not exams:
        await update.message.reply_text("No exams scheduled")
        return
    msg = "🎓 Upcoming Exams\n\n"
    for e in exams:
        delta = (datetime.strptime(e[2], "%Y-%m-%d") - datetime.now()).days
        msg  += f"[{e[0]}] {e[1]} - {e[2]} {e[3]}\n⏳ {delta} days\n\n"
    await send_long(update.message, msg)
 
async def cmd_delexam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        exam_id = int(update.message.text.replace("/delexam", "").strip())
        delete_exam(exam_id)
        await update.message.reply_text("🗑 Exam deleted")
    except:
        await update.message.reply_text("Usage: /delexam ID")
 
async def cmd_revise(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text  = update.message.text.replace("/revise", "").strip()
        parts = [p.strip() for p in text.split(",")]
        topic, subject = parts[0], parts[1]
        days = int(parts[2]) if len(parts) > 2 else 3
        add_revision(topic, subject, days)
        log_analytics("revision_added")
        await update.message.reply_text(
            f"🧠 Revision scheduled!\n📖 {topic}\n📚 {subject}\n⏰ First review in {days} days"
        )
    except:
        await update.message.reply_text("Usage: /revise topic, subject, days")
 
async def cmd_revisions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    revisions = get_all_revisions()
    if not revisions:
        await update.message.reply_text("No revisions scheduled")
        return
    msg = "🧠 Revision Schedule\n\n"
    for r in revisions:
        msg += f"📖 {r[1]} ({r[2]})\n📅 Next: {r[3]}\n\n"
    await send_long(update.message, msg)
 
async def cmd_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.replace("/note", "").strip()
    tags = " ".join([w for w in text.split() if w.startswith("#")])
    note = text.replace(tags, "").strip()
    add_note(note, tags)
    log_analytics("note_added")
    await update.message.reply_text(f"📝 Note saved!\n🏷 Tags: {tags or 'none'}")
 
async def cmd_notes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    notes = get_notes()
    if not notes:
        await update.message.reply_text("No notes yet")
        return
    msg = "📝 Notes\n\n"
    for n in notes:
        msg += f"[{n[0]}] {n[1]}\n🏷 {n[2] or 'no tags'}\n\n"
    await send_long(update.message, msg)
 
async def cmd_find(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.message.text.replace("/find", "").strip()
    results = search_notes(query)
    if not results:
        await update.message.reply_text(f"No notes found for: {query}")
        return
    msg = f"🔍 Results for '{query}'\n\n"
    for n in results:
        msg += f"[{n[0]}] {n[1]}\n🏷 {n[2]}\n\n"
    await send_long(update.message, msg)
 
async def cmd_delnote(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        note_id = int(update.message.text.replace("/delnote", "").strip())
        delete_note(note_id)
        await update.message.reply_text("🗑 Note deleted")
    except:
        await update.message.reply_text("Usage: /delnote ID")
 
async def cmd_ask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id  = update.message.from_user.id
    question = update.message.text.replace("/ask", "").strip()
    if not question:
        await update.message.reply_text("Usage: /ask your question")
        return
    if user_id not in conversation_history:
        conversation_history[user_id] = []
    conversation_history[user_id].append({"role": "user", "content": question})
    if len(conversation_history[user_id]) > 10:
        conversation_history[user_id] = conversation_history[user_id][-10:]
    thinking_msg = await update.message.reply_text("🤔 Thinking...")
    try:
        loop  = asyncio.get_event_loop()
        reply = await asyncio.wait_for(
            loop.run_in_executor(None, chat_with_history, conversation_history[user_id]),
            timeout=25
        )
    except asyncio.TimeoutError:
        reply = "❌ Took too long. Try again."
    conversation_history[user_id].append({"role": "assistant", "content": reply})
    log_analytics("ai_ask")
    await edit_long(thinking_msg, f"🤖 {reply}")

async def cmd_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    message = " ".join(context.args).strip()
    if not message:
        await update.message.reply_text("Usage: /chat tell me something interesting")
        return
    if user_id not in conversation_history:
        conversation_history[user_id] = []
    conversation_history[user_id].append({"role": "user", "content": message})
    if len(conversation_history[user_id]) > 10:
        conversation_history[user_id] = conversation_history[user_id][-10:]
    thinking_msg = await update.message.reply_text("💬 Chatting...")
    try:
        loop  = asyncio.get_event_loop()
        reply = await asyncio.wait_for(
            loop.run_in_executor(None, chat_with_history, conversation_history[user_id]),
            timeout=25
        )
    except asyncio.TimeoutError:
        reply = "❌ Took too long. Try again."
    conversation_history[user_id].append({"role": "assistant", "content": reply})
    log_analytics("ai_ask")
    await edit_long(thinking_msg, f"🤖 {reply}")
 
async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    conversation_history[user_id] = []
    await update.message.reply_text("🔄 Conversation reset!")
 
async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clear both conversation history and memory."""
    user_id = update.message.from_user.id
    # Clear conversation history
    conversation_history[user_id] = []
    # Clear memory from database
    try:
        conn = get_conn()
        conn.execute("DELETE FROM memory")
        conn.commit()
        conn.close()
        await update.message.reply_text("🧹 Your history and memory have been reset!")
    except Exception as e:
        await update.message.reply_text(f"🔄 Conversation reset! ⚠️ Memory clear failed: {e}")
 
 
async def cmd_explain(update: Update, context: ContextTypes.DEFAULT_TYPE):
    topic        = update.message.text.replace("/explain", "").strip()
    thinking_msg = await update.message.reply_text("📖 Explaining...")
    loop         = asyncio.get_event_loop()
    reply        = await loop.run_in_executor(None, explain_simple, topic)
    await edit_long(thinking_msg, f"💡 {reply}")
 
async def cmd_summarize(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text         = update.message.text.replace("/summarize", "").strip()
    thinking_msg = await update.message.reply_text("📝 Summarizing...")
    loop         = asyncio.get_event_loop()
    reply        = await loop.run_in_executor(None, summarize_text, text)
    await edit_long(thinking_msg, f"📋 {reply}")
 
async def cmd_decide(update: Update, context: ContextTypes.DEFAULT_TYPE):
    question     = update.message.text.replace("/decide", "").strip()
    thinking_msg = await update.message.reply_text("🧭 Analyzing...")
    loop         = asyncio.get_event_loop()
    reply        = await loop.run_in_executor(None, decision_helper, question)
    log_analytics("ai_decide")
    await edit_long(thinking_msg, f"🧭 {reply}")
 
async def cmd_studyplan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text     = update.message.text.replace("/studyplan", "").strip()
        parts    = [p.strip() for p in text.split(",")]
        subjects = parts[0]
        days     = int(parts[1]) if len(parts) > 1 else 7
        thinking_msg = await update.message.reply_text("📚 Generating study plan...")
        loop     = asyncio.get_event_loop()
        reply    = await loop.run_in_executor(None, study_plan, subjects, days)
        log_analytics("study_plan_generated")
        await edit_long(thinking_msg, f"📚 Study Plan\n\n{reply}")
    except:
        await update.message.reply_text("Usage: /studyplan subjects, days")
 
async def cmd_idea(update: Update, context: ContextTypes.DEFAULT_TYPE):
    topic        = update.message.text.replace("/idea", "").strip()
    thinking_msg = await update.message.reply_text("🚀 Generating viral ideas...")
    loop         = asyncio.get_event_loop()
    reply        = await loop.run_in_executor(None, viral_ideas, topic)
    log_analytics("idea_generated")
    await edit_long(thinking_msg, f"🎬 {reply}")
 
async def cmd_caption(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text     = update.message.text.replace("/caption", "").strip()
    parts    = text.split(",")
    topic    = parts[0].strip()
    platform = parts[1].strip() if len(parts) > 1 else "instagram"
    thinking_msg = await update.message.reply_text("✍️ Writing caption...")
    loop     = asyncio.get_event_loop()
    reply    = await loop.run_in_executor(None, generate_caption, topic, platform)
    log_analytics("caption_generated")
    await edit_long(thinking_msg, f"📱 {reply}")
 
async def cmd_savecontent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text  = update.message.text.replace("/savecontent", "").strip()
        parts = [p.strip() for p in text.split(",")]
        ctype, content = parts[0], parts[1]
        platform = parts[2] if len(parts) > 2 else ""
        add_content(ctype, content, platform)
        await update.message.reply_text(f"💾 Saved to idea bank!\n🏷 {ctype} | {platform}")
    except:
        await update.message.reply_text("Usage: /savecontent type, content, platform")
 
async def cmd_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    items = get_content()
    if not items:
        await update.message.reply_text("Idea bank is empty")
        return
    msg = "💡 Idea Bank\n\n"
    for i in items:
        msg += f"[{i[0]}] {i[1]} | {i[3]}\n{i[2]}\n\n"
    await send_long(update.message, msg)
 
async def cmd_inbox(update: Update, context: ContextTypes.DEFAULT_TYPE):
    items = get_inbox(processed=0)
    if not items:
        await update.message.reply_text("📥 Inbox is empty!")
        return
    msg = "📥 Inbox\n\n"
    for i in items:
        msg += f"[{i[0]}] {i[1]}\n🕐 {i[2]}\n\n"
    await send_long(update.message, msg)
 
async def cmd_done_inbox(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        inbox_id = int(update.message.text.replace("/done_inbox", "").strip())
        process_inbox_item(inbox_id)
        await update.message.reply_text("✅ Inbox item processed")
    except:
        await update.message.reply_text("Usage: /done_inbox ID")
 
async def cmd_remember(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text  = update.message.text.replace("/remember", "").strip()
        key, value = [p.strip() for p in text.split(":", 1)]
        set_memory(key, value)
        await update.message.reply_text(f"🧠 Remembered!\n{key} = {value}")
    except:
        await update.message.reply_text("Usage: /remember key: value")
 
async def cmd_memory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    memories = get_all_memory()
    if not memories:
        await update.message.reply_text("No memories stored")
        return
    msg = "🧠 Memory\n\n"
    for m in memories:
        msg += f"• {m[0]}: {m[1]}\n"
    await send_long(update.message, msg)
 
async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats = get_analytics_summary()
    if not stats:
        await update.message.reply_text("No stats yet")
        return
    msg = "📊 Analytics\n\n"
    for s in stats:
        msg += f"• {s[0]}: {s[1]}\n"
    await send_long(update.message, msg)
 
 
# ─────────────────────────────────────────────────────────────────────────────
# Natural-language dispatcher
# ─────────────────────────────────────────────────────────────────────────────
 
async def natural_language_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id   = update.message.from_user.id
    user_text = update.message.text.strip()
 
    thinking = await update.message.reply_text("🧠 Understanding...")
    loop = asyncio.get_event_loop()
 
    try:
        parsed = await asyncio.wait_for(
            parse_message_async(user_text, use_ai=True),
            timeout=20
        )
    except Exception as e:
        logging.error(f"NLP error: {e}")
        add_inbox(user_text)
        await thinking.edit_text("📥 Saved to inbox! (parser unavailable)")
        return
 
    if not isinstance(parsed, dict) or "command" not in parsed:
        add_inbox(user_text)
        await thinking.edit_text("📥 Saved to inbox!")
        return
 
    cmd  = parsed.get("command", "inbox_capture")
    args = parsed.get("args", {})
    logging.info(f"NLP: cmd={cmd} args={args}")
 
    if cmd == "add_task":
        try:
            add_task(
                args["date"], args["task"],
                args.get("time", "09:00"),
                args.get("category", "general")
            )
            log_analytics("task_added")
            await thinking.edit_text(
                f"✅ Task added!\n"
                f"📅 {args['date']} | {args.get('time','09:00')}\n"
                f"📝 {args['task']}\n"
                f"🏷 {args.get('category','general')}"
            )
        except Exception as e:
            await thinking.edit_text(f"❌ Couldn't add task: {e}")
 
    elif cmd == "today_tasks":
        today = datetime.now(ist).strftime("%Y-%m-%d")
        tasks = get_tasks(date=today)
        if not tasks:
            await thinking.edit_text("No tasks today! 🎉")
        else:
            msg = f"📅 Tasks for {today}\n\n"
            for t in tasks:
                icon = "✅" if t[4] == "Done" else "⏳"
                msg += f"{icon} [{t[0]}] {t[3]} - {t[2]} ({t[5]})\n"
            await edit_long(thinking, msg)
 
    elif cmd == "add_exam":
        try:
            add_exam(args["subject"], args["date"], args.get("time", "09:00"))
            log_analytics("exam_added")
            delta = (datetime.strptime(args["date"], "%Y-%m-%d") - datetime.now()).days
            await thinking.edit_text(
                f"🎓 Exam added!\n📚 {args['subject']}\n"
                f"📅 {args['date']} at {args.get('time','09:00')}\n"
                f"⏳ {delta} days remaining"
            )
        except Exception as e:
            await thinking.edit_text(f"❌ Couldn't add exam: {e}")
 
    elif cmd == "list_exams":
        exams = get_exams()
        if not exams:
            await thinking.edit_text("No exams scheduled")
        else:
            msg = "🎓 Upcoming Exams\n\n"
            for e in exams:
                delta = (datetime.strptime(e[2], "%Y-%m-%d") - datetime.now()).days
                msg  += f"[{e[0]}] {e[1]} - {e[2]} {e[3]}\n⏳ {delta} days\n\n"
            await edit_long(thinking, msg)
 
    elif cmd == "add_revision":
        try:
            add_revision(
                args["topic"],
                args.get("subject", "General"),
                int(args.get("days", 3))
            )
            log_analytics("revision_added")
            await thinking.edit_text(
                f"🧠 Revision scheduled!\n📖 {args['topic']}\n"
                f"⏰ First review in {args.get('days', 3)} days"
            )
        except Exception as e:
            await thinking.edit_text(f"❌ Couldn't schedule revision: {e}")
 
    elif cmd == "list_revisions":
        revisions = get_all_revisions()
        if not revisions:
            await thinking.edit_text("No revisions scheduled")
        else:
            msg = "🧠 Revision Schedule\n\n"
            for r in revisions:
                msg += f"📖 {r[1]} ({r[2]})\n📅 Next: {r[3]}\n\n"
            await edit_long(thinking, msg)
 
    elif cmd == "add_note":
        try:
            add_note(args["note"], args.get("tags", ""))
            log_analytics("note_added")
            await thinking.edit_text(
                f"📝 Note saved!\n🏷 Tags: {args.get('tags','none')}"
            )
        except Exception as e:
            await thinking.edit_text(f"❌ Couldn't save note: {e}")
 
    elif cmd == "list_notes":
        notes = get_notes()
        if not notes:
            await thinking.edit_text("No notes yet")
        else:
            msg = "📝 Notes\n\n"
            for n in notes:
                msg += f"[{n[0]}] {n[1]}\n🏷 {n[2] or 'no tags'}\n\n"
            await edit_long(thinking, msg)
 
    elif cmd == "ask_ai":
        question = args.get("question", user_text)
        if user_id not in conversation_history:
            conversation_history[user_id] = []
        conversation_history[user_id].append({"role": "user", "content": question})
        if len(conversation_history[user_id]) > 10:
            conversation_history[user_id] = conversation_history[user_id][-10:]
        try:
            reply = await asyncio.wait_for(
                loop.run_in_executor(None, chat_with_history, conversation_history[user_id]),
                timeout=25
            )
        except asyncio.TimeoutError:
            reply = "❌ Took too long. Try again."
        conversation_history[user_id].append({"role": "assistant", "content": reply})
        log_analytics("ai_ask")
        await edit_long(thinking, f"🤖 {reply}")
 
    elif cmd == "study_plan":
        subjects = args.get("subjects", args.get("raw", ""))
        days     = int(args.get("days", 7))
        reply    = await loop.run_in_executor(None, study_plan, subjects, days)
        log_analytics("study_plan_generated")
        await edit_long(thinking, f"📚 Study Plan\n\n{reply}")
 
    elif cmd == "stats":
        stats = get_analytics_summary()
        if not stats:
            await thinking.edit_text("No stats yet")
        else:
            msg = "📊 Analytics\n\n"
            for s in stats:
                msg += f"• {s[0]}: {s[1]}\n"
            await edit_long(thinking, msg)
 
    else:
         # Fallback to casual AI chat for free-form messages
        if user_id not in conversation_history:
            conversation_history[user_id] = []
        conversation_history[user_id].append({"role": "user", "content": user_text})
        if len(conversation_history[user_id]) > 10:
            conversation_history[user_id] = conversation_history[user_id][-10:]
        try:
            reply = await asyncio.wait_for(
                loop.run_in_executor(None, chat_with_history, conversation_history[user_id]),
                timeout=25
            )
            conversation_history[user_id].append({"role": "assistant", "content": reply})
            log_analytics("ai_ask")
            await edit_long(thinking, f"🤖 {reply}")
        except asyncio.TimeoutError:
            await thinking.edit_text("❌ Took too long. Try again.")
 
 
# ─────────────────────────────────────────────────────────────────────────────
# App setup
# ─────────────────────────────────────────────────────────────────────────────
 
def main():
    app = (
        Application.builder()
        .token(TOKEN)
        .post_init(post_init)
        .build()
    )
 
    app.add_error_handler(error_handler)
 
    app.add_handler(CommandHandler("start",       start))
    app.add_handler(CallbackQueryHandler(menu_callback))
    app.add_handler(CommandHandler("add",         cmd_add))
    app.add_handler(CommandHandler("today",       cmd_today))
    app.add_handler(CommandHandler("done",        cmd_done))
    app.add_handler(CommandHandler("deltask",     cmd_deltask))
    app.add_handler(CommandHandler("addexam",     cmd_addexam))
    app.add_handler(CommandHandler("exams",       cmd_exams))
    app.add_handler(CommandHandler("delexam",     cmd_delexam))
    app.add_handler(CommandHandler("revise",      cmd_revise))
    app.add_handler(CommandHandler("revisions",   cmd_revisions))
    app.add_handler(CommandHandler("note",        cmd_note))
    app.add_handler(CommandHandler("notes",       cmd_notes))
    app.add_handler(CommandHandler("find",        cmd_find))
    app.add_handler(CommandHandler("delnote",     cmd_delnote))
    app.add_handler(CommandHandler("ask",         cmd_ask))
    app.add_handler(CommandHandler("chat",        cmd_chat))
    app.add_handler(CommandHandler("reset",       cmd_reset))
    app.add_handler(CommandHandler("clear",       cmd_clear))
    app.add_handler(CommandHandler("explain",     cmd_explain))
    app.add_handler(CommandHandler("summarize",   cmd_summarize))
    app.add_handler(CommandHandler("decide",      cmd_decide))
    app.add_handler(CommandHandler("studyplan",   cmd_studyplan))
    app.add_handler(CommandHandler("idea",        cmd_idea))
    app.add_handler(CommandHandler("caption",     cmd_caption))
    app.add_handler(CommandHandler("savecontent", cmd_savecontent))
    app.add_handler(CommandHandler("content",     cmd_content))
    app.add_handler(CommandHandler("inbox",       cmd_inbox))
    app.add_handler(CommandHandler("done_inbox",  cmd_done_inbox))
    app.add_handler(CommandHandler("remember",    cmd_remember))
    app.add_handler(CommandHandler("memory",      cmd_memory))
    app.add_handler(CommandHandler("stats",       cmd_stats))
    app.add_handler(CommandHandler("generate",    cmd_generate))
 
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        natural_language_handler
    ))
 
    jq = app.job_queue
    jq.run_repeating(check_tasks,          interval=60,   first=10)
    jq.run_repeating(check_revisions,      interval=3600, first=30)
    jq.run_repeating(check_exam_countdown, interval=3600, first=60)
    jq.run_daily(morning_briefing, time=dtime(7,  0, tzinfo=ist))
    jq.run_daily(night_summary,    time=dtime(22, 0, tzinfo=ist))
 
    print("🚀 AI Life OS Bot Running...")
    app.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
        poll_interval=1.0,
        timeout=10
    )
 
 
if __name__ == "__main__":
    main()
 
