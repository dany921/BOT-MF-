import os
import re
import csv
from datetime import datetime
from typing import Tuple, Optional

import httpx
from fastapi import FastAPI
from pydantic import BaseModel
from dotenv import load_dotenv

# DB (SQLAlchemy)
from sqlalchemy.orm import Session
from models import Base, engine, SessionLocal, User, MessageLog

# ====== Load env ======
load_dotenv()
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TG_API_BASE = os.getenv("TELEGRAM_API_BASE", "https://api.telegram.org").strip()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()

ALLOWED_COURSE = os.getenv("ALLOWED_COURSE", "Matematica Finanziaria").strip()
TOTAL_QUOTA = int(os.getenv("TOTAL_QUOTA", "300"))           # quota totale vita
SIGNUP_PASSWORD = os.getenv("SIGNUP_PASSWORD", "sblocco").strip()
PORT = int(os.getenv("PORT", "8000"))

if not BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN mancante in .env")
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY mancante in .env")

TG_SEND = f"{TG_API_BASE}/bot{BOT_TOKEN}/sendMessage"

# ====== CSV archive ======
CSV_PATH = os.getenv("ARCHIVE_CSV_PATH", "archive.csv")
ARCHIVE = {}  # key: (YYYY-MM-DD, exercise:int) -> dict

def load_archive(csv_path: str):
    global ARCHIVE
    ARCHIVE.clear()
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            date = row["date"].strip()
            try:
                ex = int(row["exercise"])
            except:
                continue
            ARCHIVE[(date, ex)] = {
                "title": row.get("title", "").strip(),
                "result_short": row.get("result_short", "").strip(),
                "solution_steps": row.get("solution_steps", "").strip(),
                "notes": row.get("notes", "").strip(),
                "version": row.get("version", "v1").strip() or "v1",
            }

load_archive(CSV_PATH)

# ====== Parsers ======
DATE_REGEX = re.compile(r"(\d{4}-\d{2}-\d{2}|\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4})")
EX_REGEX = re.compile(r"(?:^|\b)(?:es|esercizio)\s*\.?\s*(\d{1,2})(?:\b|$)", re.IGNORECASE)

def normalize_date(raw_date: str) -> Optional[str]:
    try:
        if "-" in raw_date and len(raw_date) == 10:
            # Assume already YYYY-MM-DD
            return raw_date
        sep = "/" if "/" in raw_date else "-"
        parts = raw_date.split(sep)
        d = int(parts[0]); m = int(parts[1]); y = int(parts[2])
        if y < 100:
            y += 2000
        return f"{y:04d}-{m:02d}-{d:02d}"
    except Exception:
        return None

def parse_exam_query(text: str) -> Tuple[Optional[str], Optional[int]]:
    d = DATE_REGEX.search(text or "")
    date_str = normalize_date(d.group(1)) if d else None
    e = EX_REGEX.search(text or "")
    ex = int(e.group(1)) if e else None
    return date_str, ex

# ====== OpenAI client ======
from openai import OpenAI
oai = OpenAI(api_key=OPENAI_API_KEY)

def ai_solution_fallback(user_prompt: str) -> str:
    system = (
        "Sei un assistente per il corso di Matematica Finanziaria. "
        "Rispondi SOLO su temi in-scope (rendite, ammortamenti FR/italiano, bond base, tassi). "
        "Formatta SEMPRE così:\n"
        "[STIMA AI] Risultato: <valore sintetico>\n\n"
        "Spiegazione (passo-passo):\n1) ...\n2) ...\n3) ...\n\n"
        "Assunzioni:\n- ...\n\n"
        "Regole: importi con 2 decimali (es: € 1.234,56), tassi con 4 decimali (es: 5,1234%). "
        "Se i dati mancano, dichiaralo e proponi 1 sola ipotesi ragionevole."
    )
    resp = oai.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.2,
    )
    return resp.choices[0].message.content.strip()

# ====== FastAPI app ======
app = FastAPI()

class TelegramUpdate(BaseModel):
    update_id: int | None = None
    message: dict | None = None

async def tg_send(chat_id: int, text: str):
    async with httpx.AsyncClient(timeout=20) as client:
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
        r = await client.post(TG_SEND, json=payload)
        r.raise_for_status()

def get_or_create_user(db: Session, tg_user: dict) -> User:
    uid = tg_user["id"]
    user = db.get(User, uid)
    if not user:
        user = User(
            id=uid,
            username=tg_user.get("username"),
            first_name=tg_user.get("first_name"),
            last_name=tg_user.get("last_name"),
            is_verified=False,
            total_used=0,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    return user

def log_message(db: Session, user_id: int, text: str, kind: str = "reply", meta: str | None = None):
    log = MessageLog(user_id=user_id, text=text, kind=kind, meta=meta)
    db.add(log)
    db.commit()

# Create tables on startup
Base.metadata.create_all(bind=engine)

# ====== Moderazione base (scope) ======
def in_scope(text: str) -> bool:
    keywords = [
        "appello", "esercizio", "rendita", "ammortamento", "francese", "italiano",
        "rata", "tasso", "capitalizzazione", "attualizzazione", "bond", "cedola",
        "durata", "valore attuale", "valore futuro", "yield", "t.i.r."
    ]
    t = (text or "").lower()
    if DATE_REGEX.search(t) and EX_REGEX.search(t):
        return True
    return any(k in t for k in keywords)

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/api/telegram/webhook")
async def telegram_webhook(update: TelegramUpdate):
    if not update.message:
        return {"ok": True}

    msg = update.message
    chat_id = msg["chat"]["id"]
    from_user = msg["from"]
    text = (msg.get("text") or "").strip()

    db = SessionLocal()
    try:
        user = get_or_create_user(db, from_user)

        # Commands
        if text.lower().startswith("/start"):
            greet = (
                f"Ciao! Sono il bot di <b>{ALLOWED_COURSE}</b>.\n"
                "Per usare il bot devi prima sbloccarlo con la parola-chiave.\n"
                f"Usa: <code>/unlock {SIGNUP_PASSWORD}</code>\n\n"
                "Dopo lo sblocco puoi chiedere: <i>Appello YYYY-MM-DD es N</i> oppure esercizi.\n"
                "Comandi: /quota, /policy, /help"
            )
            await tg_send(chat_id, greet)
            return {"ok": True}

        if text.lower().startswith("/unlock"):
            parts = text.split(maxsplit=1)
            provided = parts[1].strip() if len(parts) > 1 else ""
            if provided == SIGNUP_PASSWORD:
                user.is_verified = True
                db.commit()
                await tg_send(chat_id, "✅ Sblocco riuscito! Ora puoi usare il bot.")
            else:
                await tg_send(chat_id, "❌ Parola-chiave errata. Riprova.")
            return {"ok": True}

        if text.lower().startswith("/quota"):
            await tg_send(chat_id, f"Hai usato <b>{user.total_used}/{TOTAL_QUOTA}</b> risposte totali.")
            return {"ok": True}

        if text.lower().startswith("/policy"):
            await tg_send(chat_id, "Rispondo solo su appelli passati ed esercizi di <b>Matematica Finanziaria</b>.\n"
                                   "Le risposte dall'archivio sono <b>[UFFICIALE]</b>. Altrimenti fornisco <b>[STIMA AI]</b>.")
            return {"ok": True}

        if text.lower().startswith("/help"):
            await tg_send(chat_id, "Ok! Ti metto in contatto con un tutor umano. (Handoff verrà attivato dopo il MVP)")
            return {"ok": True}

        # Require verification before any answer
        if not user.is_verified:
            await tg_send(chat_id, "🔒 Bot bloccato. Sbloccalo con: "
                                   f"<code>/unlock {SIGNUP_PASSWORD}</code>")
            return {"ok": True}

        # Enforce lifetime quota
        if user.total_used >= TOTAL_QUOTA:
            await tg_send(chat_id, "Hai esaurito la tua quota totale. Digita /help per parlare con un tutor.")
            log_message(db, user.id, text, kind="blocked", meta='{"reason":"quota_exceeded"}')
            return {"ok": True}

        # Moderazione base
        if not in_scope(text):
            await tg_send(chat_id, "Tema fuori ambito. Supporto solo: appelli passati ed esercizi di Matematica Finanziaria.")
            log_message(db, user.id, text, kind="blocked", meta='{"reason":"out_of_scope"}')
            return {"ok": True}

        # Lookup archivio
        date_str, ex_num = parse_exam_query(text)
        if date_str and ex_num:
            rec = ARCHIVE.get((date_str, ex_num))
            if rec:
                steps = rec["solution_steps"].strip()
                if steps and not steps.startswith("1)"):
                    lines = [ln.strip() for ln in steps.splitlines() if ln.strip()]
                    steps = "\n".join([f"{i+1}) {ln}" for i, ln in enumerate(lines)])
                reply = (
                    f"<b>[UFFICIALE] Risultato</b> (Appello {date_str}, Esercizio {ex_num})\n"
                    f"{rec['result_short']}\n\n"
                    f"<b>Spiegazione (tua)</b>\n{steps or '—'}\n\n"
                    f"<b>Titolo:</b> {rec['title']}\n"
                    f"<b>Note:</b> {rec['notes'] or '—'}\n"
                    f"<b>Versione:</b> {rec['version']}"
                )
                await tg_send(chat_id, reply)
                user.total_used += 1
                db.commit()
                log_message(db, user.id, text, kind="reply", meta='{"source":"official_archive"}')
                return {"ok": True}
            else:
                prompt = (f"L'utente chiede una soluzione per l'esercizio {ex_num} dell'appello {date_str}. "
                          f"Se mancano dati, dichiaralo e proponi un'ipotesi ragionevole.")
                ai_text = ai_solution_fallback(prompt)
                await tg_send(chat_id, ai_text)
                user.total_used += 1
                db.commit()
                log_message(db, user.id, text, kind="reply", meta='{"source":"ai_fallback"}')
                return {"ok": True}

        # Generic exercise → AI
        ai_text = ai_solution_fallback(text)
        await tg_send(chat_id, ai_text)
        user.total_used += 1
        db.commit()
        log_message(db, user.id, text, kind="reply", meta='{"source":"ai_generic"}')
        return {"ok": True}

    finally:
        db.close()

# Local run helper
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=True)
