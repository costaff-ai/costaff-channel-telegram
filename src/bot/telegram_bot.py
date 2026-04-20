import os
import re
import io
import time
import base64
import logging
import asyncio
from collections import defaultdict
from typing import Set

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message, FSInputFile, BotCommand

from src.core.adk_client import run_adk_prompt, delete_session, upload_to_costaff, sync_identity, check_approved, get_user_id, setup_logging
from src.core.adk_client import SessionLocal, models

setup_logging(os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

# Rate limiting: max messages per user per time window
_RATE_LIMIT_MAX = int(os.getenv("RATE_LIMIT_MAX", "10"))
_RATE_LIMIT_WINDOW = int(os.getenv("RATE_LIMIT_WINDOW", "60"))
_msg_timestamps: dict[str, list[float]] = defaultdict(list)

def _is_rate_limited(uid: str) -> bool:
    now = time.time()
    window_start = now - _RATE_LIMIT_WINDOW
    _msg_timestamps[uid] = [t for t in _msg_timestamps[uid] if t > window_start]
    if len(_msg_timestamps[uid]) >= _RATE_LIMIT_MAX:
        return True
    _msg_timestamps[uid].append(now)
    return False

# Environment variables
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
APP_NAME = os.getenv("ADK_APP_NAME", "costaff_agent")
PENDING_MSG = "⌛ 您的帳號正在等待管理員審核中..."

if not TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN is not set")

bot = Bot(token=TOKEN)
dp = Dispatcher()

_processed_message_ids: Set[int] = set()

async def safe_reply(msg: Message, text: str):
    """Replies to a message using HTML parse mode, handling potential errors."""
    try:
        await msg.reply(text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Reply error: {e}. Falling back to plain text.")
        await msg.reply(text)

@dp.message(Command("start"))
async def cmd_start(msg: Message):
    """Initiates identity check and greeting."""
    uid = get_user_id(msg.chat.id)
    sid = f"tg_{uid}"
    sync_identity(uid, str(msg.chat.id), sid)
    
    if not check_approved(sid):
        await msg.answer(PENDING_MSG)
        return

    await bot.send_chat_action(msg.chat.id, "typing")
    preferred_lang = os.getenv("COSTAFF_PREFERRED_LANGUAGE", "Traditional Chinese (繁體中文)")
    res = await run_adk_prompt(APP_NAME, uid, sid, 
                               prompt=f"(Context ID: {uid}). Please check my identity and greet me in {preferred_lang}.")
    await safe_reply(msg, res)

@dp.message(Command("reset"))
async def cmd_reset(msg: Message):
    """Clears the current conversation session."""
    uid = get_user_id(msg.chat.id)
    sid = f"tg_{uid}"
    sync_identity(uid, str(msg.chat.id), sid)
    if not check_approved(sid):
        await msg.answer(PENDING_MSG)
        return
    await bot.send_chat_action(msg.chat.id, "typing")
    if await delete_session(APP_NAME, uid, sid):
        preferred_lang = os.getenv("COSTAFF_PREFERRED_LANGUAGE", "Traditional Chinese (繁體中文)")
        res = await run_adk_prompt(APP_NAME, uid, sid,
                                   prompt=f"(Context ID: {uid}). Please check my identity and greet me in {preferred_lang}.")
        await safe_reply(msg, f"🔄 <b>對話已重設</b>\n\n{res}")
    else:
        await msg.answer("Reset failed.")

@dp.message(Command("help"))
async def cmd_help(msg: Message):
    """Displays a list of available slash commands."""
    txt = ("<b>CoStaff 指令：</b>\n"
           "/start - 開始/身份檢查\n"
           "/reset - 重設對話\n"
           "/profile - 查看個人資料\n"
           "/list - 查看提醒任務")
    await safe_reply(msg, txt)

@dp.message(Command("profile"))
async def cmd_profile(msg: Message):
    uid = get_user_id(msg.chat.id)
    sid = f"tg_{uid}"
    sync_identity(uid, str(msg.chat.id), sid)
    if not check_approved(sid):
        await msg.answer(PENDING_MSG)
        return
    await bot.send_chat_action(msg.chat.id, "typing")
    res = await run_adk_prompt(APP_NAME, uid, sid, prompt="Show my profile.")
    await safe_reply(msg, res)

@dp.message(Command("list"))
async def cmd_list(msg: Message):
    uid = get_user_id(msg.chat.id)
    sid = f"tg_{uid}"
    sync_identity(uid, str(msg.chat.id), sid)
    if not check_approved(sid):
        await msg.answer(PENDING_MSG)
        return
    await bot.send_chat_action(msg.chat.id, "typing")
    res = await run_adk_prompt(APP_NAME, uid, sid, prompt="List my reminders.")
    await safe_reply(msg, res)

async def _send_file(chat_id: str, path: str):
    """Send a file to Telegram — photos as image, everything else as document."""
    if not os.path.exists(path):
        logger.warning(f"File not found for delivery: {path}")
        return
    name = os.path.basename(path)
    ext = os.path.splitext(name)[1].lower()
    try:
        if ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"):
            await bot.send_photo(chat_id, FSInputFile(path), caption=name)
        else:
            await bot.send_document(chat_id, FSInputFile(path), caption=name)
        logger.info(f"Delivered file: {path}")
    except Exception as e:
        logger.error(f"Failed to deliver {path}: {e}")


WORKSPACE_DIR = "/app/data/coding_workspace"
REPORTS_DIR = "/app/data/reports"
FILE_SEARCH_DIRS = [WORKSPACE_DIR, REPORTS_DIR, "/app/data/outputs"]

def _resolve_path(raw: str) -> str | None:
    """Resolve a file path (absolute or relative) to an existing absolute path."""
    raw = raw.strip().strip("`")
    if os.path.isabs(raw):
        return raw if os.path.exists(raw) else None
    # Relative path: search common base directories
    for base in FILE_SEARCH_DIRS:
        candidate = os.path.join(base, raw)
        if os.path.exists(candidate):
            return candidate
    return None


async def _deliver_response(msg: Message, final_res: str):
    """Parse agent response, send text reply, and deliver any file attachments."""
    logger.debug(f"Agent response: {final_res[:100]}...")

    FILE_EXTS = r"pdf|docx|md|txt|html|htm|png|jpg|jpeg|gif|csv|json|xlsx|xls|zip"

    # 1a. [FILE: path] or (FILE: path) tags — absolute or relative
    # Use a simpler regex construction to avoid f-string escaping issues
    tag_pattern = r"[\[\(](?:FILE|檔案)[:：]\s*([^\]\)\s]+\.(?:" + FILE_EXTS + r"))[\]\)]"
    tag_paths = re.findall(tag_pattern, final_res, re.IGNORECASE)

    # 1b. Absolute /app/data/... paths
    abs_pattern = r"`?(/app/data/[\w./-]+\.(?:" + FILE_EXTS + r"))`?"
    abs_paths = re.findall(abs_pattern, final_res, re.IGNORECASE)

    # 1c. Relative paths in backticks
    rel_pattern = r"`([\w/-]+\.(?:" + FILE_EXTS + r"))`"
    rel_paths = re.findall(rel_pattern, final_res, re.IGNORECASE)

    raw_paths = list(dict.fromkeys(tag_paths + abs_paths + rel_paths))
    all_paths = [r for p in raw_paths if (r := _resolve_path(p))]

    # 2. Clean response text — replace path references with attachment hint only when files exist
    attachment_hint = "（詳見附件）" if all_paths else ""
    clean_res = re.sub(
        rf"[\[\(](?:FILE|檔案)[:：]\s*([^\]\)\s]+\.(?:{FILE_EXTS}))[\]\)]",
        attachment_hint, final_res, flags=re.IGNORECASE
    )
    clean_res = re.sub(rf"`?/app/data/[\w./-]+\.(?:{FILE_EXTS})`?", attachment_hint, clean_res, flags=re.IGNORECASE)
    clean_res = re.sub(rf"`[\w/-]+\.(?:{FILE_EXTS})`", attachment_hint, clean_res, flags=re.IGNORECASE)
    # Collapse duplicate hints that appear consecutively
    clean_res = re.sub(r"（詳見附件）(\s*（詳見附件）)+", "（詳見附件）", clean_res)
    clean_res = clean_res.strip()

    if clean_res:
        await safe_reply(msg, clean_res)
    elif not all_paths:
        await safe_reply(msg, final_res)

    # 3. Deliver files
    for path in all_paths:
        await _send_file(str(msg.chat.id), path)


async def _run_agent_task(msg: Message, uid: str, sid: str, parts: list):
    """Background task: runs ADK agent and delivers response. Errors are caught and reported to user."""
    try:
        final_res = await run_adk_prompt(APP_NAME, uid, sid, parts=parts)
        await _deliver_response(msg, final_res)
    except Exception as e:
        logger.error(f"Agent task failed for session {sid}: {e}")
        await safe_reply(msg, "很抱歉，處理您的請求時發生錯誤，請稍後再試。")


@dp.message()
async def handle_msg(msg: Message):
    """
    The main message handler for text, photos, and documents.
    Deduplicates webhook retries and runs the agent as a background task
    so Telegram does not time out on long-running requests.
    """
    # --- A: Deduplication — drop Telegram webhook retries for the same message ---
    if msg.message_id in _processed_message_ids:
        logger.info(f"Duplicate message {msg.message_id} dropped.")
        return
    _processed_message_ids.add(msg.message_id)
    if len(_processed_message_ids) > 2000:
        _processed_message_ids.clear()

    text = msg.text or msg.caption or ""
    parts = [{"text": text}] if text else []
    uid = get_user_id(msg.chat.id)
    sid = f"tg_{uid}"
    sync_identity(uid, str(msg.chat.id), sid)
    if not check_approved(sid):
        await msg.answer(PENDING_MSG)
        return

    if _is_rate_limited(uid):
        await msg.answer("⏳ 訊息太頻繁，請稍後再試。")
        return

    _MAX_MSG_LEN = int(os.getenv("MAX_MSG_LEN", "8000"))
    if len(text) > _MAX_MSG_LEN:
        await msg.answer(f"⚠️ 訊息過長（上限 {_MAX_MSG_LEN} 字元），請縮短後再試。")
        return

    UPLOADS_DIR = "/app/data/coding_workspace/shared/uploads"
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    uploaded_file_paths: list[str] = []

    if msg.photo:
        photo = msg.photo[-1]
        info = await bot.get_file(photo.file_id)
        buf = io.BytesIO()
        await bot.download_file(info.file_path, buf)
        data = base64.b64encode(buf.getvalue()).decode()
        parts.append({"inlineData": {"mimeType": "image/jpeg", "data": data}})
        # Also save to shared workspace so coding-agent can access it
        fname = f"photo_{photo.file_id}.jpg"
        fpath = os.path.join(UPLOADS_DIR, fname)
        buf.seek(0)
        with open(fpath, "wb") as f:
            f.write(buf.read())
        uploaded_file_paths.append(fpath)
        await upload_to_costaff(buf, fname, uid, sid=sid, app_name=APP_NAME)

    if msg.document:
        doc = msg.document
        info = await bot.get_file(doc.file_id)
        buf = io.BytesIO()
        await bot.download_file(info.file_path, buf)
        fname = doc.file_name or f"document_{doc.file_id}"
        fpath = os.path.join(UPLOADS_DIR, fname)
        buf.seek(0)
        with open(fpath, "wb") as f:
            f.write(buf.read())
        uploaded_file_paths.append(fpath)
        await upload_to_costaff(buf, fname, uid, sid=sid, app_name=APP_NAME)

    # Inject uploaded file paths into the agent message
    if uploaded_file_paths:
        rel_paths = [os.path.relpath(p, "/app/data/coding_workspace") for p in uploaded_file_paths]
        paths_note = (
            "（使用者上傳了以下檔案：" + ", ".join(uploaded_file_paths) + "。"
            "coding_agent 可用 read_file 工具以相對路徑存取：" + ", ".join(rel_paths) + "）"
        )
        if parts and "text" in parts[0]:
            parts[0]["text"] = parts[0]["text"] + " " + paths_note
        else:
            parts.append({"text": paths_note})

    if not parts:
        return

    await bot.send_chat_action(msg.chat.id, "typing")

    # Inject Context ID so the Agent always knows the user_id for tools
    context_text = f"(Context ID: {uid})"
    if "text" in parts[0]:
        parts[0]["text"] = f"{context_text} {parts[0]['text']}"
    else:
        parts.insert(0, {"text": context_text})

    # --- B: Fire-and-forget — return immediately, deliver result when done ---
    asyncio.create_task(_run_agent_task(msg, uid, sid, parts))

async def reset_all_sessions():
    """Proactively clears sessions and greets all known users."""
    db = SessionLocal()
    try:
        users = db.query(models.IdentityMap).all()
        latest_by_real_id: dict = {}
        for user in users:
            existing = latest_by_real_id.get(user.real_id)
            if not existing or (user.created_at and (not existing.created_at or user.created_at > existing.created_at)):
                latest_by_real_id[user.real_id] = user

        for user in latest_by_real_id.values():
            uid = get_user_id(int(user.real_id))
            sid = f"tg_{uid}"
            sync_identity(uid, user.real_id, sid)
            await delete_session(APP_NAME, uid, sid)
            preferred_lang = os.getenv("COSTAFF_PREFERRED_LANGUAGE", "Traditional Chinese (繁體中文)")
            res = await run_adk_prompt(APP_NAME, uid, sid, prompt=f"(Context ID: {uid}). Please check my identity and greet me in {preferred_lang}.")
            try:
                await bot.send_message(chat_id=user.real_id, text=f"🔄 <b>系統已重啟並自動重置</b>\n\n{res}", parse_mode="HTML")
            except Exception as e: logger.error(f"Greeting error: {e}")
    finally:
        db.close()

async def main():
    # Start a minimal health check server in background
    from aiohttp import web
    async def health_check(request):
        return web.json_response({"name": "telegram", "status": "healthy"})
    
    app = web.Application()
    app.router.add_get('/.well-known/agent.json', health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    asyncio.create_task(site.start())

    cmds = [BotCommand(command=c[0], description=c[1]) for c in [
        ("start", "開始"), ("reset", "重設"), ("help", "幫助"), ("profile", "資料"), ("list", "排程")
    ]]
    await bot.set_my_commands(cmds)
    # await reset_all_sessions() # Optional: Disable if annoying during dev
    try:
        logger.info("Starting Telegram Bot...")
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        logger.info("Telegram bot shut down gracefully.")

if __name__ == "__main__":
    asyncio.run(main())
