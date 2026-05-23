"""Tests for the Telegram-specific glue in bot/telegram_bot.py.

The heavy lifting (resolve_path, session state, dispatch) lives in the
shared costaff_channel_chatbot library — its own test suite covers
that. Here we lock in just the Telegram → IncomingMessage conversion
that this thin adapter is responsible for:

- `_attachments_of`: extract Telegram-specific photo/document fields.
- `_to_incoming`: single Telegram Message → shared IncomingMessage.
- `_to_incoming_group`: aggregate an album (media_group) into one msg.
- `TelegramAdapter._reply_params`: build aiogram ReplyParameters from
  message_id, gracefully degrade on bad input.
"""
from __future__ import annotations

import pytest

from bot.telegram_bot import (
    TelegramAdapter,
    _attachments_of,
    _to_incoming,
    _to_incoming_group,
)
from costaff_channel_chatbot import IncomingMessage
from tests.conftest import make_document as make_doc
from tests.conftest import make_msg
from tests.conftest import make_photo_size as make_photo


# ----------------------------------------------------- _attachments_of

def test_attachments_of_empty():
    msg = make_msg(text="hi")
    assert _attachments_of(msg) == []


def test_attachments_of_photo_picks_largest_size():
    """Telegram returns multiple resolutions; the adapter picks the LAST
    (largest). We verify that contract."""
    small = make_photo("small-id", width=320)
    large = make_photo("large-id", width=1280)
    msg = make_msg(photo=[small, large])
    atts = _attachments_of(msg)
    assert len(atts) == 1
    assert atts[0].file_id == "large-id"


def test_attachments_of_document():
    doc = make_doc(file_id="d1", file_name="report.pdf")
    msg = make_msg(document=doc)
    atts = _attachments_of(msg)
    assert atts == [doc]


def test_attachments_of_photo_plus_document():
    photo = make_photo("p")
    doc = make_doc("d")
    msg = make_msg(photo=[photo], document=doc)
    atts = _attachments_of(msg)
    assert len(atts) == 2
    assert atts[0].file_id == "p"
    assert atts[1].file_id == "d"


# ----------------------------------------------------- _to_incoming

def test_to_incoming_with_text():
    msg = make_msg(chat_id=555, message_id=10, text="hello")
    inc = _to_incoming(msg)
    assert isinstance(inc, IncomingMessage)
    assert inc.real_id == "555"
    assert inc.text == "hello"
    assert inc.message_id == "10"
    assert inc.attachments == []
    assert inc.raw is msg


def test_to_incoming_with_caption_when_no_text():
    """Caption (on a photo / document) becomes the message text."""
    msg = make_msg(text=None, caption="see this image", photo=[make_photo()])
    inc = _to_incoming(msg)
    assert inc.text == "see this image"
    assert len(inc.attachments) == 1


def test_to_incoming_empty_text():
    msg = make_msg(text=None, caption=None)
    inc = _to_incoming(msg)
    assert inc.text == ""


def test_to_incoming_text_wins_over_caption():
    """If both text and caption exist (rare), text takes precedence."""
    msg = make_msg(text="text", caption="caption")
    inc = _to_incoming(msg)
    assert inc.text == "text"


# ----------------------------------------------------- _to_incoming_group

def test_to_incoming_group_aggregates_photos():
    """An album of N photos → ONE IncomingMessage with N attachments."""
    m1 = make_msg(chat_id=10, message_id=1, photo=[make_photo("p1")])
    m2 = make_msg(chat_id=10, message_id=2, photo=[make_photo("p2")])
    m3 = make_msg(chat_id=10, message_id=3, photo=[make_photo("p3")])
    inc = _to_incoming_group([m1, m2, m3])
    assert isinstance(inc, IncomingMessage)
    assert inc.real_id == "10"
    assert inc.message_id == "1"  # first message's id
    assert len(inc.attachments) == 3
    assert [a.file_id for a in inc.attachments] == ["p1", "p2", "p3"]


def test_to_incoming_group_picks_first_nonempty_caption():
    """Telegram puts the caption on ONE arbitrary item; we extract from
    whichever has it."""
    m1 = make_msg(message_id=1, photo=[make_photo("p1")])  # no caption
    m2 = make_msg(message_id=2, photo=[make_photo("p2")], caption="this album")
    m3 = make_msg(message_id=3, photo=[make_photo("p3")])
    inc = _to_incoming_group([m1, m2, m3])
    assert inc.text == "this album"


def test_to_incoming_group_no_caption_anywhere():
    """If no item has caption or text, text is empty."""
    m1 = make_msg(photo=[make_photo("p1")])
    m2 = make_msg(photo=[make_photo("p2")])
    inc = _to_incoming_group([m1, m2])
    assert inc.text == ""


def test_to_incoming_group_mixed_photo_and_document():
    m1 = make_msg(message_id=1, photo=[make_photo("p1")])
    m2 = make_msg(message_id=2, document=make_doc("d1", "x.pdf"))
    inc = _to_incoming_group([m1, m2])
    assert len(inc.attachments) == 2


# ----------------------------------------------------- TelegramAdapter._reply_params

def test_reply_params_returns_none_when_no_message_id():
    adapter = TelegramAdapter()
    msg = IncomingMessage(real_id="100", text="hi", message_id=None)
    assert adapter._reply_params(msg) is None


def test_reply_params_with_valid_message_id():
    """Returns aiogram ReplyParameters with the integer message_id."""
    adapter = TelegramAdapter()
    msg = IncomingMessage(real_id="100", text="hi", message_id="42")
    rp = adapter._reply_params(msg)
    assert rp is not None
    assert rp.message_id == 42
    assert rp.allow_sending_without_reply is True


def test_reply_params_with_unparseable_message_id():
    """Bad message_id → None (graceful degrade, don't crash send)."""
    adapter = TelegramAdapter()
    msg = IncomingMessage(real_id="100", text="hi", message_id="not-a-number")
    assert adapter._reply_params(msg) is None


# ----------------------------------------------------- adapter contract

def test_adapter_platform_prefix():
    adapter = TelegramAdapter()
    assert adapter.platform_prefix == "tg"


def test_adapter_max_message_length_matches_telegram_limit():
    """Telegram's hard cap on text messages is 4096 chars."""
    adapter = TelegramAdapter()
    assert adapter.max_message_length == 4096
