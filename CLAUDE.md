# CLAUDE.md — Exam Audio Relay

> Istruzioni di progetto per Claude Code. Leggere prima di toccare il codice.
> Owner: Pl1n10 / Roberto Novara
> Stato: MVP v0.1

---

## Cos'è

Web app self-hostable per consegna audio d'esame. I docenti caricano file audio,
creano sessioni a finestra temporale, condividono link unico `/s/{token}` con gli
studenti. Lo streaming passa **sempre** dal backend, mai dal filesystem statico.

Esposizione prevista: Tailscale Funnel davanti a `127.0.0.1:8080`.

---

## Stack

- Python 3.12, FastAPI, SQLAlchemy 2.x, Alembic
- PostgreSQL 16 (in prod, in container), SQLite (in test)
- Jinja2 server-rendered, CSS vanilla, niente framework JS
- Auth: SessionMiddleware (`itsdangerous`) + bcrypt
- Container: Dockerfile + docker-compose, utente non-root, tini come PID1

---

## Invarianti di sicurezza — NON violare mai

1. **Gli audio non vengono mai serviti da static middleware o redirect.**
   Lo streaming passa solo da `/stream/{token}` dopo validazione server-side
   (`evaluate_session`). Non aggiungere mai `app.mount("/uploads", StaticFiles(...))`
   o `RedirectResponse` verso il file.

2. **Filesystem mai esposto.** Lo `stored_filename` è un random hex generato dal
   server (`storage.generate_stored_filename`). L'`original_filename` resta in DB
   come metadato. `storage.absolute_path_for` fa jail in `UPLOAD_DIR` con
   `Path.resolve` + `relative_to` — qualsiasi modifica deve preservare quel
   controllo.

3. **Validazione su ogni request.** Sia `/s/{token}` che `/stream/{token}` chiamano
   `evaluate_session` su ogni colpo: revoked, finestra temporale, teacher attivo,
   `max_access_count`. Nessuna cache stateful sulla decisione di accesso.

4. **Ownership server-side.** I dependency `get_owned_audio_file` /
   `get_owned_session` (`app/deps.py`) tagliano fuori i teacher altrui con 403.
   Il superadmin bypassa via `Role.SUPERADMIN`. Non spostare i check in template.

5. **CSRF su tutte le POST/PUT/DELETE sotto `/admin`.** Token random per sessione
   utente generato al login (`auth.login_user`), incluso in ogni form come hidden
   `csrf_token`, validato dalla dependency `auth.verify_csrf` (compare_digest).
   `/login` è escluso (pre-auth). Quando aggiungi un nuovo endpoint mutante sotto
   `/admin`, usa `dependencies=[Depends(verify_csrf)]` e includi l'hidden input
   nel form.

6. **L'ultimo superadmin attivo non si tocca.** `routes/teachers.py`
   `_active_superadmin_count` protegge disable e demote. Test:
   `test_last_active_superadmin_cannot_be_disabled_or_demoted`.

7. **Token sessione = `secrets.token_urlsafe(32)`**, non timestamp/uuid prevedibili.

8. **Password hashing = bcrypt** (rounds=12). Mai store plaintext.

---

## Layout

```
app/
  main.py              # FastAPI factory, lifespan, exception handlers
  config.py            # pydantic-settings (env)
  database.py          # engine + SessionLocal + Base
  models.py            # User, AudioFile, ExamSession, AccessLog
  auth.py              # login_user/logout_user, get_current_user, verify_csrf
  security.py          # bcrypt, token generation
  storage.py           # path jail, allowed extensions, content-type map
  session_logic.py     # evaluate_session, derive_status, log_event
  deps.py              # render(), get_owned_*, templates
  routes/
    auth.py            # /login /logout /
    admin.py           # /admin/* dashboard, files, upload, sessions
    teachers.py        # /admin/teachers/* (superadmin only)
    public.py          # /s/{token}, /stream/{token}
  templates/  static/
alembic/
  versions/0001_initial.py
tests/
  conftest.py          # tmpdir + sqlite test setup
  test_token_generation.py
  test_session_validation.py
  test_permissions.py
  test_smoke_http.py   # full HTTP happy path + CSRF
```

---

## Comandi

### Verde della suite
```bash
.venv/bin/pytest -q
```
Atteso: `19 passed`.

### Dev locale (sqlite, niente docker)
```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL=sqlite:///./data/dev.db SECRET_KEY=$(python -c 'import secrets; print(secrets.token_urlsafe(48))')
export INITIAL_ADMIN_USERNAME=admin INITIAL_ADMIN_PASSWORD=devpass
export DATA_DIR=./data UPLOAD_DIR=./data/uploads
alembic upgrade head
uvicorn app.main:app --reload --host 127.0.0.1 --port 8080
```

### Stack completo
```bash
cp .env.example .env  # editare INITIAL_ADMIN_*, SECRET_KEY
docker compose up -d --build
docker compose logs -f app
```

### Nuova migrazione Alembic
```bash
alembic revision --autogenerate -m "descrizione"
# rivedere SEMPRE il file generato prima di commit
alembic upgrade head
```

---

## Anti-pattern — NON fare

- Esporre `UPLOAD_DIR` come static mount o symlink dentro `app/static/`
- Sostituire `/stream/{token}` con un `RedirectResponse` verso il file
- Usare `uuid4()` o timestamp come token sessione (deve restare `secrets.token_urlsafe`)
- Cachare l'esito di `evaluate_session` tra request (la finestra temporale cambia)
- Aggiungere endpoint mutanti sotto `/admin` senza `verify_csrf`
- Inserire check di ownership in template invece che nelle dependency
- Loggare il `token` o l'`Authorization` cookie in chiaro
- Committare `.env`, `data/uploads/*`, dump PostgreSQL
- `git add -A` senza guardare cosa entra (esclude `.gitignore`, ma controlla)
- Toccare il path-jail in `storage.absolute_path_for` senza un test che ci giri sopra
- Mockare il DB nei test di permission (gli usano un sqlite reale, e va bene così)

---

## Convenzioni testing

- **Mai chiamare API esterne** (qui non ce ne sono — è un'app standalone — ma se
  un giorno aggiungiamo email/SMS, fixture obbligatoria).
- **DB**: SQLite in tempdir per test; le tabelle vengono create con
  `Base.metadata.create_all` nel fixture session-scoped, e ogni test pulisce le
  tabelle prima di partire (`db_session` fixture in `conftest.py`).
- **HTTP**: `TestClient` di FastAPI. Per CSRF si estrae il token con regex dalla
  pagina (`_extract_csrf` in `test_smoke_http.py`).
- **Determinismo**: i test temporali usano `datetime.now(timezone.utc)` ± delta
  ragionevoli; non si congela il clock.

---

## Decisioni di design non ovvie

- **`max_access_count` viene contato solo a `stream_start`** (non a `page_view`).
  Motivo: il refresh della pagina pubblica è un evento normale, non deve bruciare
  un accesso. Il consumo si conteggia quando il browser inizia effettivamente a
  scaricare l'audio (prima richiesta di range / richiesta full).

- **`is_first_byte_request`** in `routes/public.py` decide se loggare
  `STREAM_START`. Heuristica: nessun Range, oppure Range `bytes=0-` o `bytes=0-0`.
  I follow-up range del player (es. seek) non riloggano `STREAM_START` per non
  gonfiare l'access count. Se cambi questa euristica, aggiorna la logica
  `count_for_max` in `evaluate_session`.

- **Lifespan crea solo `DATA_DIR/uploads` e bootstrappa l'admin**, lo schema lo
  fa Alembic (entrypoint `docker-entrypoint.sh`). Non aggiungere `create_all`
  nel lifespan: fa divergere lo schema da Alembic.

- **`SESSION_COOKIE_SECURE` è `false` di default** perché in dev locale la app
  gira su http://127.0.0.1. In produzione dietro Tailscale Funnel va impostato
  a `true` nel `.env`.

- **Il `BASE_URL` è opzionale**. Se mancante, il dashboard renderizza link
  relativi tipo `/s/<token>`, comodo in dev. In prod si imposta al hostname
  Tailscale Funnel per generare link copia-incolla pronti.

---

## Limiti noti dell'MVP (vedi README per la lista completa)

- Niente rate limiting in-app (delegato a Tailscale ACL / Caddy / fail2ban)
- Niente sniffing MIME byte-level (solo controllo estensione)
- Niente QR code per i link sessione
- Niente upload batch
- Single-instance (upload dir locale)

---

## Quando riprendi una sessione

1. `git status` & `git log --oneline -n 5`
2. `pytest -q` per confermare verde
3. Se modifichi schema → migrazione Alembic + verifica `alembic upgrade head` su DB
   pulito + aggiornamento test
4. Se aggiungi route mutanti sotto `/admin` → CSRF + ownership dependency + test
