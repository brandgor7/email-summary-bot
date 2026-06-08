# CLAUDE.md — Working with AI on This Project

This file tells Claude (and other AI assistants) how to work effectively
on this codebase. It documents conventions, constraints, and what to watch out for.

---

## Project Summary

`email-summary-bot` is a multi-user email digest service.
- **Backend:** Python / FastAPI
- **Frontend:** TypeScript / Next.js on Vercel
- **DB:** SQLite via Turso
- **LLM:** Anthropic Claude (claude-haiku-4-5) for summarization
- **Integrations:** Microsoft Graph API (Outlook), Telegram Bot API

## Architecture Reference

Full architecture is documented in **[ARCHITECTURE.md](./ARCHITECTURE.md)**.

Read ARCHITECTURE.md before making any changes. After work is done, make sure ARCHITECTURE.md is updated to reflect the current state of the project based solely on the work performed.
The intent is that this file should be referenced instead of loading each source code file to find details of the project for the
task at hand that aren't directly related to the task that's being performed or that are
dependencies on the task being performed.

## Implementation Plan Reference

Step-by-step build order is in **[IMPLEMENTATION.md](./IMPLEMENTATION.md)**.
Record steps executed in that file for future reference.

---

## General Coding Principles

- **Simplicity over cleverness.** This project optimizes for maintainability
  and low cost. Avoid over-engineering.
- **Explicit over implicit.** Name things clearly. Prefer verbose variable names
  over short ones. No magic.
- **One responsibility per function.** Keep functions small and focused.
  If a function does two things, split it.
- **No premature abstraction.** Don't create base classes or generics until
  there are at least three concrete use cases.
- Don't write comments unless something in the code needs explanation. No obvious comments.

---

## Python / FastAPI Conventions

### Style
- Python 3.11+
- Type hints on all function signatures (args and return types)
- `async/await` throughout — this is an async app
- `snake_case` for variables and functions, `PascalCase` for classes
- Max line length: 100 chars
- Docstrings on all public functions (one-liner is fine)

### Structure
```
routers/     # FastAPI route handlers — thin, delegate to services
services/    # Business logic — no HTTP framework imports here
models.py    # Pydantic request/response schemas only
db.py        # DB connection and raw query helpers
```

Routers should not contain business logic. They validate input,
call a service, and return a response. Example:

```python
# ✅ Good
@router.post("/digest/preview")
async def preview_digest(req: PreviewRequest, user=Depends(get_current_user)):
    result = await summarizer.summarize_for_user(user.id, since_hours=req.since_hours)
    return result

# ❌ Bad — business logic in a route handler
@router.post("/digest/preview")
async def preview_digest(req: PreviewRequest):
    emails = await httpx.get("https://graph.microsoft.com/...")
    prompt = f"Summarize these: {emails}"
    ...
```

### Error handling
- Use `HTTPException` in routers for client errors (4xx)
- Raise domain-specific exceptions in services, catch them in routers
- Never return a 200 with an error payload — use proper HTTP status codes
- Always log unexpected errors before re-raising

### Dependencies
- Do not add a new dependency without a clear reason
- Prefer stdlib or already-installed packages
- If adding a new package, add it to `requirements.txt` immediately

---

## TypeScript / Next.js Conventions

### Style
- TypeScript strict mode (`"strict": true` in tsconfig)
- `camelCase` for variables/functions, `PascalCase` for components and types
- Prefer `const` over `let`; never use `var`
- No `any` types — use `unknown` and narrow, or define an interface

### Structure
```
app/             # Next.js App Router pages
components/      # Reusable UI components
lib/             # Pure utility functions, API client
hooks/           # Custom React hooks
types/           # Shared TypeScript interfaces
```

### API calls
- All calls to the FastAPI backend go through `lib/api.ts` — a thin axios wrapper
- Never call the backend directly from a component; use a hook or server action
- Always handle loading and error states in the UI

### Auth
- Use NextAuth.js session for app-level auth
- Attach `Authorization: Bearer <session_token>` to all backend calls
- Never expose Outlook tokens or Telegram tokens to the frontend

---

## Database Conventions

- **No ORM.** Use raw SQL via the for simplicity.
- All queries live in `db.py` as named functions — no inline SQL in services.
- Use parameterized queries always — never string-interpolate SQL.
- All timestamps stored as ISO 8601 UTC strings (`2025-01-15T08:00:00Z`).
- UUIDs for all primary keys (use `uuid.uuid4()`).

```python
# ✅ Good
await db.execute("SELECT * FROM users WHERE id = ?", [user_id])

# ❌ Bad — SQL injection risk
await db.execute(f"SELECT * FROM users WHERE id = '{user_id}'")
```

---

## Security Rules — Never Violate These

1. **Never log secrets.** No API keys, tokens, or refresh tokens in logs.
2. **Always encrypt Outlook refresh tokens** before storing in DB.
   Use `services/token_store.py` — never store plaintext.
3. **Validate the cron secret** on every `POST /digest/run` call.
   Return 403 if missing or wrong.
4. **Never send full email bodies to the LLM** unless the user explicitly enables it.
   Default to `bodyPreview` only.
5. **Scope MS Graph permissions minimally** — `Mail.Read` and `offline_access` only.
   Do not request write permissions.
6. **All secrets in environment variables.** Never committed to the repo.
   `.env.example` documents the required vars with placeholder values.

---

## The Summarization Prompt

The prompt in `services/summarizer.py` is the core product.
Treat changes to it with care:

- **Test with real emails** before committing prompt changes.
- **Keep the system prompt stable.** The user's `digest_prefs` is where
  personalization lives — don't put per-user logic in the system prompt.
- **Always request JSON output.** Parse with `json.loads()` and handle
  `json.JSONDecodeError` — the model occasionally produces malformed output.
- **Log token usage** on every call for cost monitoring.
- **Do not increase `max_tokens`** above 2000 without a clear reason.
  Haiku digests rarely need more than 1500 tokens of output.

---

## Testing Approach

- Use the unittest framework for testing.
- Each phase in `PLAN.md` has explicit verification steps — follow them.
- Before deploying any change that touches the summarization pipeline,
  run `scripts/test_summarize.py` against a real inbox.
- Critical paths to verify manually before any deploy:
  - OAuth flow completes and tokens are stored encrypted
  - Digest runs end-to-end (email fetch → summarize → Telegram)
  - Cron secret is enforced
  - Empty inbox produces a graceful result

---

## When Asking Claude for Help

### Do
- Paste the relevant file(s) and ask a specific question
- Describe what you've already tried
- Share actual error messages and stack traces
- Ask for one thing at a time

### Don't
- Ask Claude to "fix the whole backend" without context
- Trust generated SQL without reading it — always verify parameterization
- Accept code that introduces a new dependency without asking why
- Accept code that logs secrets or tokens

### Prompt tips for this project
- "Here is `services/summarizer.py`. The model is sometimes returning malformed JSON.
  Add retry logic with one retry and a fallback error response."
- "Here is the current Telegram formatter. Digests with 50+ emails exceed 4096 chars.
  Split into multiple messages."
- "Write a test script in `scripts/` that exercises the full digest pipeline
  for a hardcoded user ID and prints the result."

---
