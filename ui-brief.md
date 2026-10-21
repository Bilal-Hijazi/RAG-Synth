# Brief: chat UI for RAG-Synth

Build the chat interface in the existing SvelteKit app. Auth, the database and the backend already exist and work; your job is the pages and server code that connect them. Read the existing code first and follow its patterns.

## What already exists — reuse, don't rebuild

- **Auth:** Supabase SSR auth in `hooks.server.ts`. `event.locals.supabase` is a server client built from the user's session cookies. Email/password and Google sign-in work, with routes for callback, confirm and reset-password. Don't modify the auth routes.
- **Env:** variables are declared in `src/env.ts`. Follow that pattern.
- **Database:** schema and RLS policies are in `supabase/schema.sql`. Read it before writing any queries.
  - `chats` (id uuid, user_id, title, created_at): users can select, insert, update and delete their own.
  - `messages` (id bigint identity, chat_id, role `'user' | 'assistant'`, content, created_at): users can only **select** their own. Messages are written by the backend, never by SvelteKit.
  - `profiles` (user_id, name fields): filled in by a database trigger.
- **Backend (FastAPI):** runs locally at `http://127.0.0.1:8000`.

## Hard rules

1. **Never change the schema, RLS policies or any SQL.** If something seems to need a schema change, stop and ask.
2. **No service-role or secret Supabase key anywhere in SvelteKit.** All database access goes through `event.locals.supabase`, so RLS applies.
3. **All Supabase and FastAPI calls happen server-side only**, in `+page.server.ts` / `+layout.server.ts` load functions and form actions. Nothing from the browser.
4. **The user ID comes only from the verified session**, using the existing helper in hooks that validates the user (e.g. `safeGetSession` / `getUser`). Never take it from form data, and don't rely on `getSession()` alone.
5. **Never render user-written text as HTML.** Only assistant messages get Markdown rendering (see below).
6. No CORS, no new auth logic, no large UI libraries without asking.

## Backend contract

`POST {FASTAPI_URL}/chat`

```json
// request
{ "user_id": "<uuid>", "chat_id": "<uuid>", "question": "<string>" }
// response 200
{ "response": "<markdown string>" }
```

- FastAPI checks that the chat belongs to `user_id` (404 otherwise), loads the chat's recent history itself, answers, and **saves both the question and the answer** to `messages`. SvelteKit never inserts messages.
- Answers take several seconds.
- Add `FASTAPI_URL=http://127.0.0.1:8000` as a **private** env var, following the `src/env.ts` pattern.

## Routes

### `/chat` — layout (`+layout.server.ts` + `+layout.svelte`)
- Require a logged-in user; redirect to the login page otherwise.
- Load the user's chats (`id, title, created_at`) through `locals.supabase`, newest first.
- Sidebar: a "New chat" link to `/chat`, then the chat list linking to `/chat/[id]`, with the current chat highlighted.

### `/chat` — new chat (`+page.svelte` + `+page.server.ts`)
- An empty state with a question box.
- Form action, in this order:
  1. Get the verified user.
  2. Insert a chat via `locals.supabase` with `title` = the question trimmed to ~60 characters. Get its `id` back.
  3. Call FastAPI `/chat` with `{ user_id, chat_id, question }`.
  4. **If FastAPI fails:** delete the chat just created (via `locals.supabase`) and return `fail()` with an error message, keeping the question in the form.
  5. **If it succeeds:** `redirect(303, '/chat/' + id)`. The page load will show the saved question and answer.

### `/chat/[id]` — existing chat (`+page.server.ts` + `+page.svelte`)
- Load: select the chat by `params.id` via `locals.supabase`. If no row comes back (RLS hides other users' chats), throw a 404. Then select its messages (`id, role, content`) **ordered by `id` ascending**.
- Form action: verified user + `params.id` + the question → FastAPI `/chat`. On failure return `fail()` with a message, keeping the question. On success return normally; the load rerunning shows the new messages.

### Deleting a chat
- Each chat in the sidebar gets a delete control (e.g. an icon button shown on hover/focus, always visible on mobile), with a confirmation step before deleting.
- Implement it as a named form action **`delete` on the `/chat/[id]` page** (`+page.server.ts`). Layouts can't define form actions, so the sidebar's form posts to `/chat/{id}?/delete`, which works from any page.
- The action: verify the user, then delete the chat via `locals.supabase` by `id`. RLS only lets users delete their own chats, and the database cascade removes its messages. Don't delete messages separately.
- Afterwards: if the deleted chat is the one currently open, `redirect(303, '/chat')`. Otherwise stay on the current page; the sidebar reloads without it.

## UI behaviour

- Messages shown as a conversation: user messages as plain text, assistant messages as rendered Markdown.
- **Markdown safety:** assistant answers are LLM output, so they must not be able to inject HTML or scripts. Use a renderer with **raw HTML disabled** (e.g. markdown-it with `html: false`) or sanitize the output, and don't allow `javascript:` links.
- Use `use:enhance`. While a request is in flight: disable the send button, show the user's question in the thread straight away, and show a "Thinking…" indicator. Don't allow double submits.
- Enter sends, Shift+Enter adds a new line. The thread scrolls to the latest message.
- Errors from `fail()` appear above the input, and the typed question is kept.
- Clean, minimal styling that matches the existing app. Must work at phone width.

## Out of scope

Streaming, showing sources, renaming chats, profile pages, and any backend or database changes.

## Done when

- `npm run check` passes with no errors.
- With FastAPI running: starting a new chat redirects to `/chat/[id]` with the question and answer shown; a follow-up question in the same chat works; the sidebar lists the new chat.
- Opening `/chat/<random uuid>` gives a 404.
- Deleting the open chat redirects to `/chat`; deleting another chat removes it from the sidebar without leaving the page; in both cases its messages are gone from the database.
- Logged out, `/chat` redirects to login.
- With FastAPI stopped: sending shows an error, keeps the question, and a new-chat attempt leaves no empty chat behind.
