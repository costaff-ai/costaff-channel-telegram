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
from src.core.adk_client import create_new_session, get_active_session_id, set_active_session_id
from src.core.adk_client import SessionLocal, models

setup_logging(os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

# Rate limiting
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

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
APP_NAME = os.getenv("ADK_APP_NAME", "costaff_agent")
PENDING_MSG = "⌛ 您的帳號正在等待管理員審核中..."

if not TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN is not set")

bot = Bot(token=TOKEN)
dp = Dispatcher()

_processed_message_ids: Set[int] = set()
_TG_MAX_LEN = 4096
_TG_TRUNCATE_SUFFIX = "\n\n...(訊息過長，已截斷)"

def _truncate_tg(text: str) -> str:
    if len(text) <= _TG_MAX_LEN:
        return text
    return text[:_TG_MAX_LEN - len(_TG_TRUNCATE_SUFFIX)] + _TG_TRUNCATE_SUFFIX

async def safe_reply(msg: Message, text: str):
    text = _truncate_tg(text)
    try:
        await msg.reply(text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Reply error: {e}. Falling back to plain text.")
        try:
            await msg.reply(text)
        except Exception as e2:
            logger.error(f"Plain text reply also failed: {e2}")

DATA_ROOT = os.environ.get("SHARED_DIR", "/app/data/shared")

def _resolve_path(raw: str, wait_seconds: float = 0) -> str | None:
    """Resolve a file path (absolute or relative) to an existing absolute path.
    Includes a retry loop and intelligent subdirectory searching.
    """
    raw = raw.strip().strip("`").strip("'").strip("\"")
    fname = os.path.basename(raw)
    
    # Candidate paths to check
    candidates = []
    if os.path.isabs(raw):
        candidates.append(raw)

    # Always check common relative locations
    candidates.append(os.path.join(DATA_ROOT, raw))
    
    # Intelligent fuzzy search in agent directories
    try:
        if os.path.exists(DATA_ROOT):
            for entry in os.scandir(DATA_ROOT):
                if entry.is_dir():
                    candidates.append(os.path.join(entry.path, fname))
                    # Also try original sub-path
                    sub_part = raw.split("data/")[-1] if "data/" in raw else raw
                    candidates.append(os.path.join(entry.path, os.path.basename(sub_part)))
    except Exception: pass

    # Unique candidates only
    candidates = list(dict.fromkeys(candidates))

    # Retry loop for volume synchronization
    start_time = time.time()
    while True:
        for cand in candidates:
            if os.path.exists(cand) and os.path.isfile(cand):
                return cand
        
        if time.time() - start_time >= wait_seconds:
            break
        time.sleep(0.3)
        
    return None

async def _send_file(chat_id: str, path: str):
    if not os.path.exists(path): return
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

async def _deliver_response(msg: Message, final_res: str):
    """Simplified and robust delivery logic."""
    logger.info(f"Processing agent response (len={len(final_res)})")

    # 1. Path detection using broad regex (catches [FILE: path] or just /app/data/ path)
    # This pattern matches anything starting with /app/data/ and ending with a common extension
    FILE_EXTS = r"pdf|docx|md|txt|html|htm|png|jpg|jpeg|gif|csv|json|xlsx|xls|zip"
    
    # Matches [FILE: /path] or (FILE: /path) or just /app/data/path
    tag_pattern = r"[\[\(](?:FILE|檔案)[:：]\s*([^\]\)\s]+)[\]\)]"
    abs_pattern = r"(/app/data/[\w./-]+\.(?:" + FILE_EXTS + r"))"

    # Find all potential candidates
    tags = re.findall(tag_pattern, final_res, re.IGNORECASE)
    paths = re.findall(abs_pattern, final_res, re.IGNORECASE)
    
    candidates = list(dict.fromkeys(tags + paths))
    delivered_count = 0
    
    clean_res = final_res
    attachment_hint = "（詳見附件）"

    for raw_p in candidates:
        logger.info(f"Detected file candidate: {raw_p}")
        resolved = _resolve_path(raw_p, wait_seconds=2.0) # Wait up to 2s
        
        if resolved:
            logger.info(f"Resolved path successfully: {resolved}")
            # Replace the path in text
            clean_res = clean_res.replace(raw_p, attachment_hint)
            # Send the file
            await _send_file(str(msg.chat.id), resolved)
            delivered_count += 1
        else:
            logger.warning(f"Failed to resolve or find file: {raw_p}")

    # Remove the surrounding [FILE: ] markers if they remain
    clean_res = re.sub(r"[\[\(](?:FILE|檔案)[:：]\s*（詳見附件）\s*[\]\)]", attachment_hint, clean_res)
    # Collapse multiple hints
    clean_res = re.sub(r"(（詳見附件）\s*)+", attachment_hint, clean_res).strip()

    if delivered_count > 0:
        await safe_reply(msg, clean_res)
    else:
        # Fallback if no files were actually delivered
        await safe_reply(msg, final_res)

async def _run_agent_task(msg: Message, uid: str, sid: str, parts: list):
    try:
        final_res = await run_adk_prompt(APP_NAME, uid, sid, parts=parts)
        await _deliver_response(msg, final_res)
    except Exception as e:
        logger.error(f"Agent task failed for session {sid}: {e}")
        await safe_reply(msg, "很抱歉，處理您的請求時發生錯誤，請稍後再試。")

@dp.message(Command("reset"))
async def handle_reset(msg: Message):
    if msg.message_id in _processed_message_ids: return
    _processed_message_ids.add(msg.message_id)

    uid = get_user_id(msg.chat.id)
    default_sid = f"tg_{uid}"
    sync_identity(uid, str(msg.chat.id), default_sid)
    if not check_approved(default_sid):
        await msg.answer(PENDING_MSG)
        return

    await bot.send_chat_action(msg.chat.id, "typing")
    try:
        await delete_session(APP_NAME, uid, default_sid)
        await ensure_session(APP_NAME, uid, default_sid)
        logger.info(f"Reset: uid={uid} sid={default_sid} (deleted and recreated)")
        preferred_lang = os.getenv("COSTAFF_PREFERRED_LANGUAGE", "Traditional Chinese (繁體中文)")
        res = await run_adk_prompt(APP_NAME, uid, default_sid, prompt=f"(Context ID: {uid}) 你好，對話已重置，請重新問候我並初始化服務，使用 {preferred_lang}。")
        await _deliver_response(msg, res)
    except Exception as e:
        logger.error(f"Reset failed for uid={uid}: {e}")
        await safe_reply(msg, "重置失敗，請稍後再試。")

@dp.message()
async def handle_msg(msg: Message):
    if msg.message_id in _processed_message_ids: return
    _processed_message_ids.add(msg.message_id)
    if len(_processed_message_ids) > 2000: _processed_message_ids.clear()

    text = msg.text or msg.caption or ""
    parts = [{"text": text}] if text else []
    uid = get_user_id(msg.chat.id)
    default_sid = f"tg_{uid}"
    sid = get_active_session_id(uid, default_sid)
    sync_identity(uid, str(msg.chat.id), default_sid)
    if not check_approved(default_sid):
        await msg.answer(PENDING_MSG)
        return
    if _is_rate_limited(uid):
        await msg.answer("⏳ 訊息太頻繁，請稍後再試。")
        return

    UPLOADS_DIR = os.path.join(DATA_ROOT, "uploads")
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    uploaded_file_paths: list[str] = []

    if msg.photo:
        photo = msg.photo[-1]
        info = await bot.get_file(photo.file_id)
        buf = io.BytesIO()
        await bot.download_file(info.file_path, buf)
        data = base64.b64encode(buf.getvalue()).decode()
        parts.append({"inlineData": {"mimeType": "image/jpeg", "data": data}})
        fname = f"photo_{photo.file_id}.jpg"
        fpath = os.path.join(UPLOADS_DIR, fname)
        buf.seek(0)
        with open(fpath, "wb") as f: f.write(buf.read())
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
        with open(fpath, "wb") as f: f.write(buf.read())
        uploaded_file_paths.append(fpath)
        await upload_to_costaff(buf, fname, uid, sid=sid, app_name=APP_NAME)

    if uploaded_file_paths:
        paths_note = (f"（使用者上傳了檔案，已存放在 SHARED_DIR/uploads/：{', '.join(uploaded_file_paths)}）")
        if parts and "text" in parts[0]: parts[0]["text"] += " " + paths_note
        else: parts.append({"text": paths_note})

    if not parts: return
    await bot.send_chat_action(msg.chat.id, "typing")
    context_text = f"(Context ID: {uid})"
    if "text" in parts[0]: parts[0]["text"] = f"{context_text} {parts[0]['text']}"
    else: parts.insert(0, {"text": context_text})
    asyncio.create_task(_run_agent_task(msg, uid, sid, parts))

async def reset_all_sessions():
    db = SessionLocal()
    try:
        users = db.query(models.IdentityMap).all()
        latest_by_real_id = {}
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
            except Exception: pass
    finally: db.close()

async def main():
    from aiohttp import web
    async def health_check(request): return web.json_response({"status": "healthy"})
    app = web.Application()
    app.router.add_get('/.well-known/agent.json', health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', 8080).start()
    cmds = [BotCommand(command=c[0], description=c[1]) for c in [("start", "開始"), ("reset", "重設"), ("help", "幫助"), ("profile", "資料"), ("list", "排程")]]
    await bot.set_my_commands(cmds)
    await reset_all_sessions()
    try:
        logger.info("Starting Telegram Bot...")
        await dp.start_polling(bot)
    finally: await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
