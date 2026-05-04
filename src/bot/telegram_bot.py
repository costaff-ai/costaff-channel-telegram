"""Telegram chatbot — thin platform adapter on top of costaff-channel-chatbot."""
import asyncio
import io
import logging
import os
from typing import Any

from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import BotCommand, FSInputFile, Message
from costaff_channel_chatbot import (
    ChannelAdapter,
    ChannelRuntime,
    IncomingMessage,
    setup_logging,
)

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

    async def reply(self, msg: IncomingMessage, text: str) -> None:
        chat_id = int(msg.real_id)
        try:
            await bot.send_message(chat_id, text, parse_mode="HTML")
        except Exception as e:
            logger.error(f"reply HTML failed, falling back to plain: {e}")
            try:
                await bot.send_message(chat_id, text)
            except Exception as e2:
                logger.error(f"plain reply also failed: {e2}")

    async def send_file(self, msg: IncomingMessage, path: str) -> None:
        if not os.path.exists(path):
            return
        name = os.path.basename(path)
        ext = os.path.splitext(name)[1].lower()
        chat_id = int(msg.real_id)
        try:
            if ext in _IMAGE_EXTS:
                await bot.send_photo(chat_id, FSInputFile(path), caption=name)
            else:
                await bot.send_document(chat_id, FSInputFile(path), caption=name)
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


def _to_incoming(msg: Message) -> IncomingMessage:
    text = msg.text or msg.caption or ""
    attachments: list[Any] = []
    if msg.photo:
        attachments.append(msg.photo[-1])  # largest available size
    if msg.document:
        attachments.append(msg.document)
    return IncomingMessage(
        real_id=str(msg.chat.id),
        text=text,
        attachments=attachments,
        raw=msg,
        message_id=str(msg.message_id),
    )


@dp.message(Command("reset"))
async def on_reset(msg: Message) -> None:
    await bot.send_chat_action(msg.chat.id, "typing")
    await runtime.handle_reset(_to_incoming(msg))


@dp.message()
async def on_message(msg: Message) -> None:
    await bot.send_chat_action(msg.chat.id, "typing")
    await runtime.handle_message(_to_incoming(msg))


async def main() -> None:
    from aiohttp import web

    async def health_check(request):
        return web.json_response({"status": "healthy"})

    app = web.Application()
    app.router.add_get("/.well-known/agent-card.json", health_check)
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
