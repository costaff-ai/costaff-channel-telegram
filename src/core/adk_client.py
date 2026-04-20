import asyncio
import httpx
import os
import json
import logging
import io
import hashlib
from typing import Optional, List
from dotenv import load_dotenv

# Initialize logging and load environment variables
load_dotenv()
logger = logging.getLogger(__name__)

# ADK API Configuration
ADK_URL = os.getenv("ADK_API_BASE_URL", "http://localhost:8000")
TIMEOUT = 1800.0  # 30 minutes — long-running agent tasks

# PrivAI Integration (for file uploads)
PRIVAI_URL = os.getenv("PRIVAI_API_BASE_URL", "https://api.privai.ai")
PRIVAI_KEY = os.getenv("PRIVAI_API_KEY")

# Database/Identity Integration (Optional, used by some bots)
try:
    from sqlalchemy import Column, String, DateTime, Boolean, create_engine
    from sqlalchemy.ext.declarative import declarative_base
    from sqlalchemy.orm import sessionmaker
    from datetime import datetime

    Base = declarative_base()
    class IdentityMap(Base):
        __tablename__ = "identity_maps"
        session_id = Column(String, primary_key=True)
        hashed_id = Column(String, index=True, nullable=False)
        real_id = Column(String, nullable=False)
        is_approved = Column(Boolean, default=False, nullable=False)
        created_at = Column(DateTime, default=datetime.utcnow)
        updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    db_uri = os.getenv("ADK_SESSION_SERVICE_URI", "sqlite:///./costaff_agent.db")
    engine = create_engine(db_uri.replace("postgresql+asyncpg://", "postgresql://"))
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    models = type('obj', (object,), {'IdentityMap': IdentityMap})
except ImportError:
    SessionLocal = None
    models = None

def get_user_id(real_id: any) -> str:
    """Generates a stable 16-char hex ID from a platform-specific ID."""
    salt = os.getenv("ID_SALT", "costaff_default_salt")
    return hashlib.sha256(f"{real_id}{salt}".encode()).hexdigest()[:16]

def sync_identity(hashed_id: str, real_id: str, session_id: str):
    """Saves the mapping between hashed ID and real platform ID."""
    if not SessionLocal:
        logger.warning("sync_identity: SessionLocal not available, skipping")
        return
    db = SessionLocal()
    try:
        m = db.query(models.IdentityMap).filter(models.IdentityMap.session_id == session_id).first()
        if not m:
            logger.info(f"sync_identity: creating new identity for session_id={session_id}")
            db.add(models.IdentityMap(session_id=session_id, hashed_id=hashed_id, real_id=real_id, is_approved=False))
        else:
            m.real_id = real_id
            m.hashed_id = hashed_id
        db.commit()
        logger.info(f"sync_identity: committed session_id={session_id}")
    except Exception as e:
        logger.error(f"sync_identity: DB error for session_id={session_id}: {e}")
        db.rollback()
    finally:
        db.close()

def check_approved(session_id: str) -> bool:
    """Check if user is approved. Defaults to False if DB not configured."""
    if not SessionLocal:
        logger.warning("check_approved: SessionLocal not available, denying by default")
        return False
    db = SessionLocal()
    try:
        m = db.query(models.IdentityMap).filter(models.IdentityMap.session_id == session_id).first()
        result = m.is_approved if m else False
        logger.info(f"check_approved: session_id={session_id}, is_approved={result}, record_exists={m is not None}")
        return result
    except Exception as e:
        logger.error(f"check_approved: DB error for session_id={session_id}: {e}")
        return False
    finally:
        db.close()

async def upload_to_costaff(file_content: io.BytesIO, filename: str, user_id: str, sid: str = None, app_name: str = "costaff_agent") -> str:
    if not PRIVAI_KEY: return None
    metadata = json.dumps({"owner_id": user_id, "source": "channel_upload"})
    headers = {"Authorization": f"Bearer {PRIVAI_KEY}"}
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            file_content.seek(0)
            files = {
                "file": (filename, file_content),
                "metadata": (None, metadata),
                "instant_parse": (None, json.dumps({"parsing_mode": "HQ"}))
            }
            res = await client.post(f"{PRIVAI_URL}/v1/files", headers=headers, files=files, params={"purpose": "user_data"})
            return res.json().get("id") if res.status_code == 200 else None
        except Exception: return None

# ADK API Logic
_session_locks: dict[str, asyncio.Lock] = {}
_session_locks_meta: dict[str, int] = {}
_locks_registry_lock = asyncio.Lock()

async def _get_session_lock(sid: str) -> asyncio.Lock:
    async with _locks_registry_lock:
        if sid not in _session_locks:
            _session_locks[sid] = asyncio.Lock()
            _session_locks_meta[sid] = 0
        _session_locks_meta[sid] += 1
        return _session_locks[sid]

async def _release_session_lock(sid: str) -> None:
    async with _locks_registry_lock:
        if sid in _session_locks_meta:
            _session_locks_meta[sid] -= 1
            if _session_locks_meta[sid] <= 0:
                _session_locks.pop(sid, None)
                _session_locks_meta.pop(sid, None)

async def ensure_session(app: str, uid: str, sid: str) -> bool:
    url = f"{ADK_URL}/apps/{app}/users/{uid}/sessions"
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        try:
            res = await client.post(url, json={"sessionId": sid, "state": {}})
            return res.status_code in [200, 201, 409]
        except Exception: return False

async def delete_session(app: str, uid: str, sid: str) -> bool:
    url = f"{ADK_URL}/apps/{app}/users/{uid}/sessions/{sid}"
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        try:
            res = await client.delete(url)
            return res.status_code == 200
        except Exception: return False

async def run_adk_prompt(app: str, uid: str, sid: str, prompt: Optional[str] = None, parts: Optional[List[dict]] = None) -> str:
    await ensure_session(app, uid, sid)
    lock = await _get_session_lock(sid)
    try:
        async with lock:
            msg_parts = parts if parts else ([{"text": prompt}] if prompt else [])
            payload = {"appName": app, "userId": uid, "sessionId": sid, "newMessage": {"role": "user", "parts": msg_parts}}
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                for _ in range(3):
                    try:
                        res = await client.post(f"{ADK_URL}/run", json=payload)
                        if res.status_code == 200:
                            for event in reversed(res.json()):
                                if event.get("author") != "user" and "content" in event:
                                    txts = [p.get("text", "") for p in event["content"].get("parts", []) if "text" in p]
                                    if txts: return "".join(txts).strip()
                            # Nudge if silent
                            preferred_lang = os.getenv("COSTAFF_PREFERRED_LANGUAGE", "Traditional Chinese (繁體中文)")
                            payload["newMessage"] = {"role": "user", "parts": [{"text": f"任務已完成，請用{preferred_lang}向用戶說明結果摘要。"}]}
                            continue
                    except Exception: await asyncio.sleep(2)
                return "⚠️ 無法取得 Agent 回應。"
    finally: await _release_session_lock(sid)
