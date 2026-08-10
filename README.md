# Gmail Manager

A local-first Gmail management application designed as a modular monolith with a
Next.js frontend, FastAPI backend, and PostgreSQL database.

## Milestone 1: project foundation

This repository currently contains only the project foundation:

- Next.js / React frontend scaffold
- FastAPI backend scaffold
- Local PostgreSQL Docker Compose configuration
- SQLAlchemy session and configuration setup
- Alembic migration setup and an empty baseline migration
- A local owner user is automatically provisioned when the backend starts
- macOS Keychain token-store abstraction (no OAuth flow or Gmail tokens yet)

Gmail integration, user accounts, and application features intentionally begin
in later milestones.

Milestone 3 adds Gmail OAuth, macOS Keychain-only refresh-token storage,
account connect/disconnect and manual sync controls, and the Dashboard,
Intelligence, and Accounts views. PostgreSQL stores account metadata and the
messages/intelligence required by those views; it does not store OAuth tokens
or OAuth credential metadata.

The current deterministic classifier is M5.1 (`m5.1-local`).  Each thread
retains its earlier M3 and M5.0 classifications as non-current history.

## Local setup

1. Copy `.env.example` to `.env` and replace the placeholder secrets.
2. Start PostgreSQL:

   ```sh
   docker compose -f infra/docker-compose.yml up -d
   ```

3. Create and activate a Python virtual environment, then install backend
   dependencies. Recreating it with `python3` also repairs a stale virtual
   environment after a Homebrew Python upgrade:

   ```sh
   cd backend
   python3 -m venv --clear .venv
   source .venv/bin/activate
   pip install -e '.[dev]'
   ```

4. Apply database migrations:

   ```sh
   alembic upgrade head
   ```

5. Install the frontend:

   ```sh
   cd ../frontend
   npm install
   ```

6. From the repository root, start both services:

   ```sh
   make dev
   ```

The frontend is available at `http://localhost:3000`; the backend health check
is available at `http://localhost:8000/health`.

## Database changes

All schema changes must be created as Alembic migrations from `backend/`:

```sh
alembic revision --autogenerate -m "describe change"
alembic upgrade head
```
