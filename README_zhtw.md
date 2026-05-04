# CoStaff 頻道 — Telegram

[![Python Version](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/)
[![Docker Support](https://img.shields.io/badge/docker-supported-blue.svg)](https://www.docker.com/)
[![aiogram](https://img.shields.io/badge/aiogram-3.x-blue.svg)](https://docs.aiogram.dev/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://www.apache.org/licenses/LICENSE-2.0)

**[English](./README.md)** | 繁體中文

**CoStaff 頻道 — Telegram** 是 [CoStaff](https://github.com/costaff-ai/costaff) 平台的官方 Telegram Bot 插件。它透過 A2A 協議，將 Telegram 使用者與 CoStaff Agent 串接，支援文字、圖片與檔案附件。

---

## 目錄

- [運作方式](#運作方式)
- [功能特色](#功能特色)
- [Bot 指令](#bot-指令)
- [快速開始](#快速開始)
- [環境變數](#環境變數)
- [專案架構](#專案架構)
- [授權](#授權)

---

## 運作方式

```
Telegram 使用者
     │
     │  Telegram Bot API (aiogram)
     ▼
costaff-channel-telegram  ──►  CoStaff Agent (A2A / ADK API)
```

1. 使用者向 Telegram Bot 發送訊息
2. 頻道驗證使用者身份（雜湊處理，從不儲存原始 ID）並確認審核狀態
3. 訊息連同圖片或文件一併轉發給 CoStaff Agent
4. Agent 的回應傳回給使用者，檔案附件會自動偵測並以 Telegram 附件方式發送

---

## 功能特色

- **文字、圖片、文件支援** — 使用者上傳的檔案會存入共享工作區並轉交給 Agent
- **檔案自動回傳** — Agent 回應中包含檔案路徑（PDF、DOCX、圖片、CSV 等）時，會自動以附件形式傳送
- **身份審核流程** — 新使用者須等待管理員從 CoStaff 後台審核後方可使用
- **會話管理** — `/reset` 可清除對話並重新開始
- **訊息頻率限制** — 可設定每位使用者的訊息頻率上限，防止濫用
- **健康端點** — 於 8080 port 提供 `GET /.well-known/agent-card.json`，供 CoStaff 平台註冊使用

---

## Bot 指令

| 指令 | 說明 |
|---|---|
| `/start` | 註冊身份並收到個人化問候 |
| `/reset` | 清除目前對話並重新問候 |
| `/help` | 顯示所有可用指令 |
| `/profile` | 查看您的使用者資料 |
| `/list` | 列出您的排程提醒 |

---

## 快速開始

### 前置需求

- Docker 與 Docker Compose
- 正在運行的 [CoStaff](https://github.com/costaff-ai/costaff) 核心服務
- Telegram Bot Token（從 [@BotFather](https://t.me/BotFather) 取得）

### 透過 CoStaff CLI 部署

```bash
# 在 costaff-channel-telegram 目錄下執行
cst channel deploy --local .
```

CoStaff 會讀取 `costaff.channel.json`，自動建置容器並連接至平台網路。

### 手動 Docker Compose

```bash
cp .env.example .env   # 填入您的設定值
docker compose up -d --build
```

---

## 環境變數

| 變數名稱 | 必填 | 預設值 | 說明 |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | ✅ | — | 從 @BotFather 取得的 Bot Token |
| `ADK_API_BASE_URL` | ❌ | `http://costaff-agent-costaff:8080` | CoStaff Agent ADK API 位址 |
| `ADK_APP_NAME` | ❌ | `costaff_agent` | ADK 應用程式名稱 |
| `COSTAFF_PREFERRED_LANGUAGE` | ❌ | `Traditional Chinese (繁體中文)` | Agent 回應語言 |
| `RATE_LIMIT_MAX` | ❌ | `10` | 每位使用者在時間窗口內的訊息上限 |
| `RATE_LIMIT_WINDOW` | ❌ | `60` | 頻率限制時間窗口（秒） |
| `MAX_MSG_LEN` | ❌ | `8000` | 訊息最大字元數 |
| `LOG_LEVEL` | ❌ | `INFO` | 日誌等級（`DEBUG`、`INFO`、`WARNING`） |

---

## 專案架構

```
costaff-channel-telegram/
├── src/
│   ├── bot/
│   │   └── telegram_bot.py     # aiogram Bot — 指令、訊息處理、檔案回傳
│   └── core/
│       └── adk_client.py       # ADK API 客戶端、身份雜湊、會話管理
├── Dockerfile
├── docker-compose.yaml
├── costaff.channel.json        # CoStaff 頻道註冊描述檔
└── requirements.txt
```

Bot 以單一 Docker 容器運行，加入 `costaff_default` 網路，並掛載 `costaff_data` Volume 以存取外部 Agent 產出的共享工作區檔案。

---

## 授權

依 Apache 2.0 授權條款發布。詳見 `LICENSE`。
