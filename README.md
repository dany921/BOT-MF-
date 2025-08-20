# Telegram Exam Bot (V2 – quota totale + sblocco con password + DB SQLite)

Funzioni:
- Lookup archivio **[UFFICIALE]**: risultato + **spiegazione tua** dal CSV.
- Fallback **[STIMA AI]** se l'esercizio non è in archivio.
- Moderazione base: solo Matematica Finanziaria.
- **Quota totale a vita** per utente (default 300), **senza** rate-limit.
- **Sblocco con parola-chiave**: `/unlock <password>` (configurabile).
- **DB SQLite** (SQLAlchemy) per persistenza utenti e log.

## Struttura
```
.
├─ main.py
├─ models.py
├─ archive.csv
├─ env.example  (rinominalo in .env)
├─ requirements.txt
├─ run.sh
└─ scripts/
   ├─ set_webhook.sh
   └─ remove_webhook.sh
```

## Setup
1) Rinomina `env.example` → `.env` e inserisci `TELEGRAM_BOT_TOKEN` e `OPENAI_API_KEY`.
   - Opzionale: cambia `SIGNUP_PASSWORD` e `TOTAL_QUOTA`.

2) Installa e avvia:
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
./run.sh
```
Visita `http://127.0.0.1:8000/health` → `{"ok": true}`

3) Webhook (modifica `scripts/set_webhook.sh` con il tuo dominio pubblico):
```bash
bash scripts/set_webhook.sh
```

## Uso su Telegram
- `/start` → istruzioni + mostra parola-chiave richiesta per `/unlock`.
- `/unlock sblocco` → abilita l'utente (puoi cambiare la password nel `.env`).
- `Appello 2025-10-17 es 1` → **[UFFICIALE]** (dal CSV, con la tua spiegazione).
- `Appello 2025-10-17 es 99` → **[STIMA AI]**.
- `/quota` → mostra consumate/limite totale.
- `/policy`, `/help`.

## CSV – come compilarlo
Una riga per esercizio:
```
date,exercise,title,result_short,solution_steps,notes,version
2025-10-17,1,"Rendita posticipata","€ 12.345,67","1) ...
2) ...
3) ...","Anno commerciale 360",v1
```
`solution_steps` può essere multilinea: se non inizia con `1)`, verrà numerato automaticamente.

## Note tecniche
- DB SQLite: file `bot.db` creato automaticamente alla prima esecuzione.
- Modelli pronti per migrare in Django: tabelle `users` (id, is_verified, total_used, …) e `message_logs`.
- Nessun rate-limit: solo controllo quota totale.
