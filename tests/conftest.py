"""pytest fixtures for the Telegram adapter.

`bot/telegram_bot.py` reads TELEGRAM_BOT_TOKEN at import and instantiates
`aiogram.Bot(token=...)` + a `Dispatcher` as module-level state. We set
a dummy token before any import so the module loads without erroring.
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest


# Set BEFORE any import of bot.telegram_bot — module-level check fails fast.
# aiogram validates token format (digits:35-char-string), so we use a shape-
# correct dummy. The token is never sent anywhere — we mock all bot methods.
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "123456789:AAEXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX")


def make_msg(
    *,
    chat_id: int = 100,
    message_id: int = 42,
    text: str | None = None,
    caption: str | None = None,
    photo: list | None = None,
    document=None,
    media_group_id: str | None = None,
):
    """Build a MagicMock that quacks like an aiogram Message."""
    msg = MagicMock()
    msg.chat.id = chat_id
    msg.message_id = message_id
    msg.text = text
    msg.caption = caption
    msg.photo = photo  # aiogram returns list of PhotoSize (different resolutions)
    msg.document = document
    msg.media_group_id = media_group_id
    return msg


def make_photo_size(file_id: str = "photo-x", width: int = 800):
    """Build a MagicMock for PhotoSize."""
    p = MagicMock()
    p.file_id = file_id
    p.width = width
    # PhotoSize has no file_name — duck-typed check in download_attachment
    del p.file_name
    return p


def make_document(file_id: str = "doc-x", file_name: str = "report.pdf"):
    """Build a MagicMock for Document."""
    d = MagicMock()
    d.file_id = file_id
    d.file_name = file_name
    return d


@pytest.fixture
def msg_factory():
    """Convenience fixture so tests can spawn fake Messages."""
    return make_msg


@pytest.fixture
def photo_factory():
    return make_photo_size


@pytest.fixture
def doc_factory():
    return make_document
