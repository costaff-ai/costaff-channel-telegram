"""Telegram chatbot — thin platform adapter on top of costaff-channel-chatbot."""
import asyncio
import io
import logging
import os
from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import BotCommand, FSInputFile, Message, ReplyParameters
from costaff_channel_chatbot import (
    ChannelAdapter,
    ChannelRuntime,
    IncomingMessage,
    setup_logging,
)

from bot import __version__

setup_logging(os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN is not set")

bot = Bot(token=TOKEN)
dp = Dispatcher()

_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")


class TelegramAdapter(ChannelAdapter):
    platform_prefix = "tg"
    max_message_length = 4096

    def _reply_params(self, msg: IncomingMessage) -> ReplyParameters | None:
        """Build a ReplyParameters object so the outgoing message quotes the
        user's inbound message. allow_sending_without_reply=True means the
        send still succeeds (without quoting) if the target was deleted."""
        if not msg.message_id:
            return None
        try:
            return ReplyParameters(
                message_id=int(msg.message_id),
                allow_sending_without_reply=True,
            )
        except (TypeError, ValueError):
            return None

    async def reply(self, msg: IncomingMessage, text: str) -> None:
        chat_id = int(msg.real_id)
        reply_params = self._reply_params(msg)
        try:
            await bot.send_message(chat_id, text, parse_mode="HTML", reply_parameters=reply_params)
        except Exception as e:
            logger.error(f"reply HTML failed, falling back to plain: {e}")
            try:
                await bot.send_message(chat_id, text, reply_parameters=reply_params)
            except Exception as e2:
                logger.error(f"plain reply also failed: {e2}")

    async def send_file(self, msg: IncomingMessage, path: str) -> None:
        if not os.path.exists(path):
            return
        name = os.path.basename(path)
        ext = os.path.splitext(name)[1].lower()
        chat_id = int(msg.real_id)
        reply_params = self._reply_params(msg)
        try:
            if ext in _IMAGE_EXTS:
                await bot.send_photo(chat_id, FSInputFile(path), caption=name, reply_parameters=reply_params)
            else:
                await bot.send_document(chat_id, FSInputFile(path), caption=name, reply_parameters=reply_params)
            logger.info(f"Delivered file: {path}")
        except Exception as e:
            logger.error(f"Failed to deliver {path}: {e}")

    async def download_attachment(self, attachment: Any) -> tuple[bytes, str]:
        # Duck-typed: Document has .file_name, PhotoSize does not.
        info = await bot.get_file(attachment.file_id)
        buf = io.BytesIO()
        await bot.download_file(info.file_path, buf)
        fname = getattr(attachment, "file_name", None) or f"photo_{attachment.file_id}.jpg"
        return buf.getvalue(), fname

    async def push(self, real_id: str, text: str) -> None:
        try:
            await bot.send_message(int(real_id), text, parse_mode="HTML")
        except Exception as e:
            logger.warning(f"push to {real_id} failed: {e}")


adapter = TelegramAdapter()
runtime = ChannelRuntime(adapter)


def _attachments_of(msg: Message) -> list[Any]:
    atts: list[Any] = []
    if msg.photo:
        atts.append(msg.photo[-1])  # largest available size
    if msg.document:
        atts.append(msg.document)
    return atts


def _to_incoming(msg: Message) -> IncomingMessage:
    return IncomingMessage(
        real_id=str(msg.chat.id),
        text=msg.text or msg.caption or "",
        attachments=_attachments_of(msg),
        raw=msg,
        message_id=str(msg.message_id),
    )


def _to_incoming_group(msgs: list[Message]) -> IncomingMessage:
    """Aggregate an album (messages sharing media_group_id) into ONE message.

    Telegram delivers an album as N separate updates, the caption set on
    only one of them. Collect every photo/document and the single caption
    so the agent sees one multimodal Q&A turn instead of N fragments.
    """
    first = msgs[0]
    text = ""
    for m in msgs:  # caption can be on any item; take the first non-empty
        if m.caption or m.text:
            text = m.caption or m.text
            break
    attachments: list[Any] = []
    for m in msgs:
        attachments.extend(_attachments_of(m))
    return IncomingMessage(
        real_id=str(first.chat.id),
        text=text,
        attachments=attachments,
        raw=first,
        message_id=str(first.message_id),
    )


# --- Album aggregation -------------------------------------------------
# Telegram splits a multi-photo send into N updates sharing
# `media_group_id`. Buffer them and flush once, ~1.5s after the LAST
# item arrives (timer reset on each new item), so the agent gets a
# single multi-image message. Single (non-album) messages bypass this.
_MG_DEBOUNCE_SEC = 1.5
_media_groups: dict[str, dict[str, Any]] = {}


async def _flush_media_group(mgid: str) -> None:
    try:
        await asyncio.sleep(_MG_DEBOUNCE_SEC)
    except asyncio.CancelledError:
        return  # a newer item arrived; a fresh timer will flush
    grp = _media_groups.pop(mgid, None)
    if not grp or not grp["messages"]:
        return
    msgs = grp["messages"]
    try:
        await bot.send_chat_action(msgs[0].chat.id, "typing")
        await runtime.handle_message(_to_incoming_group(msgs))
    except Exception as e:
        logger.warning(f"media-group {mgid} flush failed: {e}")


@dp.message(Command("reset"))
async def on_reset(msg: Message) -> None:
    await bot.send_chat_action(msg.chat.id, "typing")
    await runtime.handle_reset(_to_incoming(msg))


@dp.message()
async def on_message(msg: Message) -> None:
    if msg.media_group_id:
        mgid = str(msg.media_group_id)
        grp = _media_groups.setdefault(mgid, {"messages": [], "task": None})
        grp["messages"].append(msg)
        if grp["task"]:
            grp["task"].cancel()  # reset debounce: flush after the LAST item
        grp["task"] = asyncio.create_task(_flush_media_group(mgid))
        return
    await bot.send_chat_action(msg.chat.id, "typing")
    await runtime.handle_message(_to_incoming(msg))


async def main() -> None:
    from aiohttp import web

    async def health_check(request):
        return web.json_response({"status": "healthy"})

    async def version_endpoint(request):
        return web.json_response({"version": __version__})

    app = web.Application()
    app.router.add_get("/.well-known/agent-card.json", health_check)
    app.router.add_get("/version", version_endpoint)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", 8080).start()

    await bot.set_my_commands([
        BotCommand(command=c, description=d)
        for c, d in [
            ("start", "開始"),
            ("reset", "重設"),
            ("help", "幫助"),
            ("profile", "資料"),
            ("list", "排程"),
        ]
    ])
    await runtime.restore_sessions()

    try:
        logger.info("Starting Telegram Bot...")
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
