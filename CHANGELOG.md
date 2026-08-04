# Changelog

All notable changes to this project are recorded here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[SemVer](https://semver.org/).

## [Unreleased]

## [0.1.0] - 2026-08-04

First stable release, aligned with the CoStaff v0.1.0 ecosystem release.

### Changed

- Pinned the shared chatbot library to `v0.1.0` (was `v0.1.0-beta-3`).

## [0.1.0-alpha-2] - 2026-06-14

### Changed

- Markdown → HTML rendering now goes through the shared formatter, with a
  plain-text fallback when an HTML push is rejected.
- Version bumped to `0.1.0-alpha-2`.

## [0.1.0-alpha-1] - 2026-05-27

First tagged pre-release. Pre-open-source cleanup pass.

### Added

- `CHANGELOG.md` (this file).
- `bot.__version__` constant and `GET /version` HTTP endpoint on the
  health server for deploy verification.
- `costaff.channel.json` now declares `ID_SALT` under `env_required`
  (`costaff channel add` will prompt for it at deploy time) and
  `public_port` 18090 so the CLI knows which port to advertise.

### Changed

- **Trimmed `requirements.txt`** to direct deps only: `aiogram`,
  `aiohttp`, `python-dotenv`, and the CoStaff SDK. Removed unused
  wrong-channel SDKs (`discord.py`, `line-bot-sdk`), agent-side
  packages (`python-docx`, `fpdf2`, `mcp`), and transitive deps the
  SDK already pulls in (`sqlalchemy`, `asyncpg`, `psycopg2-binary`,
  `httpx`, `pydantic`, `fastapi`, `uvicorn`, `apscheduler`, `pytz`,
  `python-multipart`, `cryptography`, `pyyaml`). Pinned `aiogram` to
  `>=3.10,<4` for reproducible builds.
- Renamed `.env.template` → `.env.example` to match GitHub / IDE
  conventions and the sister channel repos.
- `.env.example`: `ID_SALT` placeholder reads as `REPLACE_WITH_A_RANDOM_STRING`
  instead of `change-me-to-a-random-string`; database password and
  user reduced to `<placeholders>` so no real-looking credential ships
  in the template.

### Removed

- Local `costaff_agent.db` test artifact (now gitignored via `*.db`).

## [0.1.0]

Initial implementation. See git history for details.
