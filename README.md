# CoStaff Channel — Telegram

[![Python Version](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/)
[![Docker Support](https://img.shields.io/badge/docker-supported-blue.svg)](https://www.docker.com/)
[![aiogram](https://img.shields.io/badge/aiogram-3.x-blue.svg)](https://docs.aiogram.dev/)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)

[繁體中文](./README_zhtw.md) | **English**

**CoStaff Channel — Telegram** is the official Telegram bot plugin for the [CoStaff](https://github.com/costaff-ai/costaff) platform. It bridges your Telegram users to the CoStaff Agent via the A2A protocol, supporting text, photos, and file attachments.

---

## Table of Contents

- [How It Works](#how-it-works)
- [Features](#features)
- [Bot Commands](#bot-commands)
- [Getting Started](#getting-started)
- [Environment Variables](#environment-variables)
- [Architecture](#architecture)
- [License](#license)

---

## How It Works

```
Telegram User
     │
     │  Telegram Bot API (aiogram)
     ▼
costaff-channel-telegram  ──►  CoStaff Agent (A2A / ADK API)
```

1. A user sends a message to the Telegram bot
2. The channel authenticates the user's identity (hashed, never stored raw) and checks approval status
3. The message — along with any photos or documents — is forwarded to the CoStaff Agent
4. The agent's response is delivered back to the user, with file attachments auto-detected and sent

---

## Features

- **Text, photo, and document support** — user uploads are saved to the shared workspace and forwarded to the agent
- **File delivery** — agent responses containing file paths (PDF, DOCX, images, CSV, etc.) are automatically sent as Telegram attachments
- **Identity approval workflow** — new users are held pending until an operator approves them from the CoStaff dashboard
- **Session management** — `/reset` clears the conversation and starts fresh
- **Rate limiting** — configurable per-user message rate cap to prevent abuse
- **Health endpoint** — exposes `GET /.well-known/agent.json` on port 8080 for CoStaff platform registration

---

## Bot Commands

| Command | Description |
|---|---|
| `/start` | Register identity and receive a personalised greeting |
| `/reset` | Clear current conversation session and re-greet |
| `/help` | List all available commands |
| `/profile` | View your stored user profile |
| `/list` | List your scheduled reminders |

---

## Getting Started

### Prerequisites

- Docker and Docker Compose
- A running [CoStaff](https://github.com/costaff-ai/costaff) core stack
- A Telegram Bot Token (from [@BotFather](https://t.me/BotFather))

### Deploy via CoStaff CLI

```bash
# From within the costaff-channel-telegram directory
cst channel deploy --local .
```

CoStaff reads `costaff.channel.json`, builds the container, and connects it to the platform network automatically.

### Manual Docker Compose

```bash
cp .env.example .env   # fill in your values
docker compose up -d --build
```

---

## Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | ✅ | — | Bot token from @BotFather |
| `ADK_API_BASE_URL` | ❌ | `http://costaff-agent:8080` | CoStaff Agent ADK API base URL |
| `ADK_APP_NAME` | ❌ | `costaff_agent` | ADK application name |
| `COSTAFF_PREFERRED_LANGUAGE` | ❌ | `Traditional Chinese (繁體中文)` | Language for agent responses |
| `RATE_LIMIT_MAX` | ❌ | `10` | Max messages per user per window |
| `RATE_LIMIT_WINDOW` | ❌ | `60` | Rate limit window in seconds |
| `MAX_MSG_LEN` | ❌ | `8000` | Maximum message length in characters |
| `LOG_LEVEL` | ❌ | `INFO` | Logging level (`DEBUG`, `INFO`, `WARNING`) |

---

## Architecture

```
costaff-channel-telegram/
├── src/
│   ├── bot/
│   │   └── telegram_bot.py     # aiogram bot — commands, message handler, file delivery
│   └── core/
│       └── adk_client.py       # ADK API client, identity hashing, session management
├── Dockerfile
├── docker-compose.yaml
├── costaff.channel.json        # CoStaff channel registration manifest
└── requirements.txt
```

The bot runs as a single Docker container, joins the `costaff_default` network, and mounts the `costaff_costaff_data` volume to access shared workspace files produced by external agents.

---

## License

Distributed under the AGPL v3 License. See `LICENSE` for details.
