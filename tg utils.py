"""
tg_utils.py — Telegram helper utilities
=========================================
send_long()  — splits any text across multiple messages (4096 char limit)
edit_long()  — edits first chunk, sends rest as new messages
"""
 
import asyncio
 
TELEGRAM_LIMIT = 4096
 
 
def _split(text: str, limit: int = TELEGRAM_LIMIT) -> list[str]:
    """
    Split text into chunks of at most `limit` chars.
    Tries to break at newlines first, then spaces, then hard-cuts.
    """
    if len(text) <= limit:
        return [text]
 
    chunks = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break
 
        # Try to cut at last newline within limit
        cut = text.rfind("\n", 0, limit)
        if cut == -1:
            # Try last space
            cut = text.rfind(" ", 0, limit)
        if cut == -1:
            # Hard cut
            cut = limit
 
        chunks.append(text[:cut].strip())
        text = text[cut:].strip()
 
    return [c for c in chunks if c]
 
 
async def send_long(message, text: str, parse_mode: str = None, **kwargs):
    """
    Send text to Telegram, automatically splitting at 4096 chars.
    Use instead of update.message.reply_text() for long content.
    """
    chunks = _split(text)
    sent = []
    for i, chunk in enumerate(chunks):
        if i == 0:
            m = await message.reply_text(
                chunk, parse_mode=parse_mode, **kwargs
            )
        else:
            await asyncio.sleep(0.1)   # small delay to preserve order
            m = await message.reply_text(chunk, parse_mode=parse_mode)
        sent.append(m)
    return sent
 
 
async def edit_long(thinking_msg, text: str, parse_mode: str = None):
    """
    Edit the 'thinking' placeholder with first chunk,
    send remaining chunks as new messages.
    Replaces thinking.edit_text() for long content.
    """
    chunks = _split(text)
 
    # Edit the first message (the "🧠 Understanding..." placeholder)
    await thinking_msg.edit_text(
        chunks[0], parse_mode=parse_mode
    )
 
    # Send the rest as follow-up messages in the same chat
    for chunk in chunks[1:]:
        await asyncio.sleep(0.1)
        await thinking_msg.get_bot().send_message(
            chat_id=thinking_msg.chat_id,
            text=chunk,
            parse_mode=parse_mode
        )
 
