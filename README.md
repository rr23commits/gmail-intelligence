# Gmail Intelligence

Gmail Intelligence is a local-first personal Gmail workspace. It imports one or more Gmail accounts, stores the information needed to organize their conversations, applies a deterministic local classifier, and presents a daily briefing, inbox intelligence views, cleanup candidates, tasks, and Gmail actions.

It is a modular monolith: a Next.js browser UI, a FastAPI API, and PostgreSQL run as separate local processes. OAuth refresh tokens are stored in the current macOS user's Keychain, not in PostgreSQL.

 **Scope:** this is currently a single-local-owner application, not a multi-user hosted service. It requires a local-app password before API access and should remain behind localhost/private infrastructure unless it gains full user identity, deployment, and operations support.

## What it does

- Connects Gmail accounts through Google OAuth.
- Imports Gmail threads and messages incrementally using Gmail history IDs after the first sync.
- Classifies inbox conversations into a priority score, category, decision bucket, and evidence-backed explanation.
- Shows a dashboard, intelligence feed, account views, sender groups, learned preferences, cleanup groups, and generated action tasks.
- Lets the signed-in local owner archive, move to Trash, mark read/unread, and reply to a thread through Gmail.
- Learns account-scoped category corrections after repeated consistent feedback from the same sender domain.

## Architecture

| Component | Location | Responsibility |
| --- | --- | --- |
| Frontend | `frontend/` | Next.js 16 / React 19 browser UI on port 3000. |
| Backend | `backend/` | FastAPI API, OAuth callback, Gmail integration, classification, and authorization on port 8000. |
| Database | PostgreSQL 16 via `infra/docker-compose.yml` | Gmail metadata/content, classifications, feedback, tasks, and sync history. |
| Secret storage | macOS Keychain | Gmail refresh tokens, indexed by application Gmail-account UUID. |
| Schema changes | `backend/alembic/` | Versioned Alembic migrations. |

### Core terms

| Term | Meaning |
| --- | --- |
| Local owner | The one application user provisioned from `LOCAL_OWNER_EMAIL`; it owns every connected Gmail account in this local deployment. |
| Gmail account | A Gmail mailbox authorized through OAuth and associated with the local owner. |
| Thread | A Gmail conversation stored with a Gmail thread ID and local UUID. |
| Message | A stored Gmail message containing sender/recipient data, subject, snippet, body text, labels, and delivery facts needed by classification. |
| Classification | An immutable result for a thread. Only one result is current; previous versions remain historical. |
| Decision bucket | UI grouping: `do`, `consider`, or `clean_up`. |
| Action task | A locally extracted task from a message, with title, optional deadline, and `open`, `done`, or `snoozed` status. |
| Sync run | An auditable manual synchronization attempt with counts, status, and an error summary when it fails. |

## Requirements

- macOS (the token store uses the macOS Keychain)
- Python 3.12+
- Node.js 20+
- Docker Desktop / Docker Compose
- A Google OAuth client configured with the callback URL below

## Configuration

Copy `.env.example` to `.env`, fill every placeholder, and protect it:

```sh
cp .env.example .env
chmod 600 .env
```

| Variable | Required | Definition |
| --- | --- | --- |
| `DATABASE_URL` | Yes | SQLAlchemy PostgreSQL URL. Its password must exactly match `POSTGRES_PASSWORD`. |
| `POSTGRES_PASSWORD` | Yes | Password for the local `gmail_manager` PostgreSQL role used by Compose. |
| `APP_ENV` | Yes | `development` locally; use a non-development value only behind HTTPS. |
| `APP_SECRET_KEY` | Yes | Long random secret used to sign session and OAuth-state values. |
| `LOCAL_AUTH_PASSWORD` | Yes | Password shown at the local browser sign-in screen. It is never sent to the frontend configuration. |
| `LOCAL_OWNER_EMAIL` | Yes | Identifier for the single local application owner; it is not a Gmail identity. |
| `LOCAL_OWNER_DISPLAY_NAME` | No | Display name for the local owner. |
| `GOOGLE_OAUTH_CLIENT_ID` | Yes for Gmail | Google OAuth client ID. |
| `GOOGLE_OAUTH_CLIENT_SECRET` | Yes for Gmail | Google OAuth client secret. |
| `GOOGLE_OAUTH_REDIRECT_URI` | Yes for Gmail | Default: `http://localhost:8000/api/v1/auth/gmail/callback`. Register this exact URL with Google. |
| `FRONTEND_URL` | Yes | Allowed browser origin; default: `http://localhost:3000`. |
| `NEXT_PUBLIC_API_BASE_URL` | Yes | Browser-visible backend base URL; default: `http://localhost:8000`. This value must never contain a secret. |

Generate random values with `openssl rand -hex 32`. Do not commit `.env`; `.gitignore` excludes it and other local secret/data artifacts.

## First-time setup

1. Configure `.env` as above. Use the same generated database password in both `DATABASE_URL` and `POSTGRES_PASSWORD`.
2. Start PostgreSQL. `--env-file .env` is required because the Compose file lives in `infra/`.

   ```sh
   docker compose --env-file .env -f infra/docker-compose.yml up -d postgres
   ```

   PostgreSQL is published only to `127.0.0.1:5432`.

3. Create and install the backend environment.

   ```sh
   cd backend
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -e '.[dev]'
   alembic upgrade head
   ```

4. Install frontend dependencies.

   ```sh
   cd ../frontend
   npm install
   ```

5. From the repository root, start both development servers.

   ```sh
   make dev
   ```

6. Open `http://localhost:3000`, sign in with `LOCAL_AUTH_PASSWORD`, then choose **Connect Gmail**.

## Everyday commands

| Goal | Command |
| --- | --- |
| Start PostgreSQL | `docker compose --env-file .env -f infra/docker-compose.yml up -d postgres` |
| Stop PostgreSQL | `docker compose --env-file .env -f infra/docker-compose.yml down` |
| Start app servers | `make dev` |
| Run backend tests | `cd backend && .venv/bin/pytest -q` |
| Lint backend | `cd backend && .venv/bin/ruff check app tests` |
| Production frontend build | `cd frontend && npm run build` |
| Apply migrations | `cd backend && .venv/bin/alembic upgrade head` |
| Check API health | `curl http://127.0.0.1:8000/health` |

## Security model

- `POST /api/v1/auth/login` accepts the local password and returns an HttpOnly, signed, expiring session cookie.
- Every application data/Gmail route requires that session. The health endpoint remains public.
- OAuth start requires a session. The callback validates a signed, expiring state and a matching short-lived HttpOnly nonce cookie before exchanging a code.
- CORS permits only `FRONTEND_URL` and cookie-bearing browser requests.
- API requests are rate-limited in process: 60 requests/minute per client/path, and 10/minute for sync, reply, and thread-action paths. This is intentionally local/single-process protection, not a distributed rate limiter.
- Request limits cap reply bodies at 10,000 characters and a thread-action request at 100 thread IDs.
- PostgreSQL is loopback-only in Compose. Its password is not committed.
- Gmail refresh tokens are Keychain-only. PostgreSQL deliberately has no access-token or refresh-token columns.

For a production or multi-user deployment, add a real identity provider, shared rate limiting, HTTPS/reverse-proxy configuration, backup encryption, monitoring, and multi-user authorization.

## Gmail permissions and actions

The OAuth request asks for these scopes:

| Scope | Used for |
| --- | --- |
| `gmail.readonly` | Reading mailbox/profile data during connection and synchronization. |
| `gmail.modify` | Archive, Trash, and read/unread changes. |
| `gmail.send` | Replying to a thread. |

The backend verifies that selected local thread IDs belong to the requested account before Gmail actions are issued. Gmail IDs are encoded before use in API paths. Disconnecting an account deletes its Keychain refresh token and the account's cascaded local records.

## Classification and decisions

The current classifier is deterministic and local: **M5.1** (`m5.1-local`). It normalizes visible text, examines recipient/delivery context, detects tasks, deadlines, verification codes, records, opportunities, notifications, broadcast/promotional signals, and assigns:

- one of `action_required`, `opportunity`, `important_keep`, `personal_conversation`, `notification`, `otp_verification`, `promotional_bulk`, or `unclear`;
- a 0–100 priority score;
- confidence and a compact explanation.

Decision buckets are derived as follows:

| Bucket | Categories |
| --- | --- |
| `do` | `action_required` |
| `consider` | `opportunity`, `important_keep`, `personal_conversation` |
| `clean_up` | All remaining categories |

Explicit corrections create immutable feedback/classification records. Two consistent corrections for the same sender domain and original category may adjust later classifications for that account; OTP classifications are not overridden. The `jobs/` modules support append-only semantic-shadow evaluation and promotion experiments, but the shipped application classifier is local and deterministic.

## Data retained locally

PostgreSQL retains connected-account metadata; Gmail thread/message IDs; sender/recipient information; subjects, snippets, decoded body text, labels, and limited delivery metadata; classifications; feedback; action tasks; and sync-run history. It does **not** retain refresh tokens.

This is sensitive email data. Keep the database local, protect host backups, and disconnect an account when its local data should be removed.

## API reference

All `/api/v1` routes below require the local session unless marked otherwise. FastAPI also exposes development documentation at `/docs` and `/openapi.json`.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| GET | `/health` | Public health check. |
| GET | `/api/v1/auth/session` | Current local-session status. |
| POST | `/api/v1/auth/login` | Creates a local session. |
| POST | `/api/v1/auth/logout` | Clears the local session. |
| POST | `/api/v1/auth/gmail/start` | Starts authenticated Google OAuth. |
| GET | `/api/v1/auth/gmail/callback` | Google OAuth callback; validates state/nonce. |
| GET | `/api/v1/accounts` | Connected Gmail accounts. |
| POST | `/api/v1/accounts/{account_id}/sync` | Manual account synchronization. |
| GET | `/api/v1/accounts/{account_id}/sync-runs` | Five most recent sync runs. |
| POST | `/api/v1/accounts/{account_id}/threads/action` | Archive, delete-to-Trash, mark read, or mark unread. |
| POST | `/api/v1/accounts/{account_id}/threads/{thread_id}/reply` | Send a Gmail reply. |
| DELETE | `/api/v1/accounts/{account_id}` | Disconnect the account and remove local data. |
| GET | `/api/v1/intelligence` | Filtered/paginated intelligence feed. |
| GET | `/api/v1/intelligence/{thread_id}` | Conversation, message, explanation, and task detail. |
| POST | `/api/v1/intelligence/{thread_id}/classification-feedback` | Save an explicit category correction. |
| GET | `/api/v1/intelligence/overview` | Category and decision counts. |
| GET | `/api/v1/intelligence/senders` | Sender-domain groups. |
| GET | `/api/v1/intelligence/learned-preferences` | Account feedback-derived preferences. |
| GET | `/api/v1/intelligence/cleanup` | Grouped cleanup recommendations. |
| POST | `/api/v1/accounts/{account_id}/tasks/{task_id}/status` | Set task status. |
| GET | `/api/v1/dashboard` | Daily briefing data. |

## Database migrations

Alembic is the schema source of truth. Create schema changes from `backend/` and commit the generated migration with the model change:

```sh
cd backend
.venv/bin/alembic revision --autogenerate -m "describe change"
.venv/bin/alembic upgrade head
```

The current migration chain is:

| Revision | Change |
| --- | --- |
| `20260804_0001` | Baseline. |
| `20260804_0002` | Users, Gmail accounts, messages, threads, classifications, sync state/runs, and related ownership constraints. |
| `20260807_0003` | Removes OAuth credential metadata so tokens remain Keychain-only. |
| `20260807_0004` | Adds message delivery metadata and classification validation constraints. |
| `20260810_0005` | Adds account-scoped classification feedback. |
| `20260811_0006` | Adds action tasks. |

## Milestones and differences

| Milestone | Main change compared with the prior milestone |
| --- | --- |
| M1 — Foundation | Introduced the Next.js/FastAPI/PostgreSQL skeleton, settings, Alembic, and local owner. No Gmail integration yet. |
| M2 — Identity/account foundation | Added users, account ownership, account-scoped schema constraints, and Keychain token-store abstraction. |
| M3 — Gmail integration | Added OAuth, Keychain refresh-token storage, account connection/disconnection, Gmail synchronization, and initial Dashboard/Accounts/Intelligence UI. |
| M4 — Intelligence pipeline | Added stored threads/messages, deterministic classification, explanations, inbox feed/detail views, Gmail actions, and cleanup workflow. |
| M5.0 — Classification refinement | Expanded deterministic categories, priority/confidence scoring, history, and semantic-shadow job scaffolding. |
| M5.1 — Visible-text and feedback refinement | Improved local rule quality by removing HTML/URL noise, added delivery context, immutable feedback, and learned sender preferences. |
| M5.2 — Decisions/tasks/UI | Added `do`/`consider`/`clean_up` views, extracted action tasks and deadlines, dashboard refinements, related conversation links, sync logs, and performance/UI polish. |
| Current security hardening | Added local password sessions, OAuth nonce/expiry binding, rate/request limits, safer error redirects, loopback-only PostgreSQL, secret hygiene, and API response security headers. |

## Repository layout

```text
backend/
  app/                 FastAPI application, domain services, models, security, classifier, jobs
  alembic/             Schema migrations
  tests/               Backend test suite and Gmail fixtures
frontend/
  app/                 Next.js routes, layout, client shell, and styling
  lib/api-client/      Typed browser API client
infra/
  docker-compose.yml   Local PostgreSQL service
.env.example           Required local configuration template
Makefile               Starts backend and frontend together
```

## Troubleshooting

- **Compose says `POSTGRES_PASSWORD` is missing:** use `docker compose --env-file .env -f infra/docker-compose.yml ...` from the repository root.
- **The browser returns 401:** sign in at `http://localhost:3000` with `LOCAL_AUTH_PASSWORD`; restart `make dev` after changing `.env`.
- **OAuth is not configured:** set the Google client ID, secret, and exact redirect URI, then restart the backend.
- **OAuth callback fails state validation:** begin the connection again from the signed-in browser; state is intentionally short-lived and one-use at the browser level.
- **Keychain errors:** Gmail token storage is macOS-only; run the app as the macOS user that authorized the account.
- **Database connection errors after a password rotation:** confirm `DATABASE_URL` and `POSTGRES_PASSWORD` match, then recreate PostgreSQL with `--force-recreate`.
