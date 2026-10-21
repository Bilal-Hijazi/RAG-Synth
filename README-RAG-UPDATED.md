# RAG-Synth

Retrieval-augmented chat over a synthetic enterprise corpus: 25 finance, HR and legal documents for a fictional Dubai SaaS company, Meridian Technologies Inc. Users sign in, open chats, and ask questions in natural language; answers are grounded in the documents, with follow-up questions understood in context.

The retrieval focus is the part naive RAG gets wrong: **tables**. Budgets, income statements and invoices hold the figures people actually ask about, and plain vector search is bad at finding exact numbers inside them.

## Results

Retrieval evaluation on the 13 questions in `evals.json` that have source documents, comparing three retriever setups:

| Retriever | Chunks per question | Strict hit rate | Mean source recall |
| --- | --- | --- | --- |
| Dense, top-2 (LlamaIndex default) | 2 | 69% (9/13) | 81% |
| Dense, top-8 | 8 | 85% (11/13) | 92% |
| **Hybrid: dense top-5 + keyword top-5** | 6–9 (avg 7.8) | **92% (12/13)** | **96%** |

*Strict hit rate:* every expected source document was retrieved. *Mean source recall:* the share of expected source documents retrieved. Per-question results are in `results@dense2.jsonl`, `results@dense8.jsonl` and `results@5+5_hybrid.jsonl`.

What each step changed:

- **More chunks (2 → 8)** fixed two questions where the right document ranked just below the cut-off: the Q4 2024 net income lookup (F2), and the Employee Handbook half of the procurement-audit question (C2).
- **Hybrid over dense at roughly the same chunk count** fixed one more: the Saudi expansion question (C4). It names the Series B outright, and keyword search pulled in the Series B board resolution that dense retrieval ranked too low.
- **Still failing in every setup:** C1, a two-hop question (see [Known limitations](#known-limitations)).

The hybrid retriever returns the union of the dense top-5 and the keyword top-5 with duplicates removed, which is why its chunk count varies. The two lists overlapped by only about two chunks per question, so dense and keyword search mostly surface different material.

With 13 questions, one question is worth about 8 points. The gap between hybrid and dense top-8 is a single question: directional, not conclusive.

> **Correction:** an earlier version of this README reported 69% / 81% as a hybrid top-5 result. That run actually used LlamaIndex's default retriever (dense, top-2), because the eval built its own retriever without the hybrid settings. Re-running the default reproduced 69% / 81% exactly; the eval retriever is now configured explicitly.

### The case that shaped the design

> *"What is the FY2025 budget for G&A expenses?"* (answer: AED 6,700,000, from a table in the FY2025 budget plan)

- **Dense retrieval, top-5:** five chunks from the right document came back, but they were the budget assumptions and section headings, not the expense table. The model correctly said it couldn't find the figure.
- **Hybrid retrieval:** correct, AED 6,700,000.
- **Dense retrieval, top-8:** also correct.

The table chunk ranked just outside dense's top 5. Its similarity score sat in the same 0.69–0.72 band as the chunks above it, so a small embedding model barely separates them. Keyword search and a wider dense window both get it into the candidate set. That points at the next step: retrieve wide, then rerank down to the few chunks the model actually needs.

It also shows a limit of document-level scoring: every setup counts as a hit on this question, including dense top-2, because they all retrieve *some* chunk of the budget plan. Only some of them retrieve the right section.

## How it works

```
                        ┌──────────── Browser ────────────┐
                        │  sign in · chat list · chat UI  │
                        └───────────────┬─────────────────┘
                                        │ form actions (server-side only)
                        ┌───────────────▼─────────────────┐
                        │ SvelteKit server                │
                        │  · Supabase session (cookies)   │
                        │  · reads chats/messages via RLS │
                        │  · creates/deletes chats via RLS│
                        └───────┬─────────────────┬───────┘
         POST /chat             │                 │ user-scoped queries
  {user_id, chat_id, question}  │                 │
                        ┌───────▼───────┐   ┌─────▼──────────────────────┐
                        │ FastAPI       │──►│ Supabase Postgres          │
                        │  · ownership  │   │  chats · messages (RLS)    │
                        │  · history    │   │  profiles (RLS + trigger)  │
                        │  · retrieval  │   │  pgvector + full-text      │
                        │  · LLM answer │   │  document store            │
                        │  · saves msgs │   └────────────────────────────┘
                        └───────────────┘

Ingestion (offline):
.docx ──► markitdown ──► Markdown (tables preserved) ──► MarkdownElementNodeParser
     ├── text sections ──► text nodes
     └── tables ────────► LLM summary + full table
──► bge-small-en-v1.5 embeddings ──► pgvector table + document store
```

A chat turn:

1. The SvelteKit form action takes the user from the verified session and the chat from the URL, and calls FastAPI. A new chat is created first, through RLS, with the first question as its title.
2. FastAPI confirms the chat belongs to that user, loads the chat's last 10 messages, and builds a fresh chat engine for the request.
3. The engine rewrites follow-ups into standalone questions ("and the year before?" becomes a full question), retrieves with hybrid search, and answers only from the retrieved context.
4. FastAPI saves the question and the answer in one insert, and SvelteKit reloads the chat.

## API

| Endpoint | What it does |
| --- | --- |
| `POST /chat` | One chat turn. Body: `{"user_id": "<uuid>", "chat_id": "<uuid>", "question": "..."}`. Returns `{"response": "..."}`. Returns 404 if the chat doesn't exist or isn't that user's. |

The API is internal: only the SvelteKit server calls it, and it is not exposed to browsers.

## Design decisions

### Retrieval
- **Convert .docx to Markdown before loading.** The default .docx reader flattens tables into loose lines of text, so numbers lose their column headers. markitdown keeps them as proper Markdown tables.
- **Summarise tables, but keep the full table.** `MarkdownElementNodeParser` gives each table an LLM-written summary alongside the table itself. The summary describes what the table is about, which matches questions better than raw numbers; the table gives the model the actual figures.
- **One vector table, department as metadata.** Every document is tagged `legal`, `financial` or `hr` and stored together. Cross-department questions retrieve from everything at once, and filtering by department is still available.
- **Hybrid search.** Financial and legal questions hinge on exact terms ("G&A", "Q4 2024", "Series B") that embeddings blur. Postgres full-text search runs alongside vector search on the same table. In the eval it recovered a cross-department document that dense search missed at the same chunk count.
- **Grounded answers.** The chat prompt restricts answers to the retrieved context and the conversation, and tells the model to say when the documents don't contain the answer, rather than falling back on general knowledge.
- **Idempotent ingestion.** A Postgres document store with stable file-based IDs (`filename_as_id`) and the `upserts` strategy means re-running ingestion skips unchanged files, instead of duplicating chunks and regenerating table summaries.

### Application
- **The web app talks to everything server-side.** All Supabase and FastAPI calls happen in SvelteKit form actions and load functions. The browser only ever sees the app.
- **RLS for everything users touch.** `chats` and `messages` are protected by row-level security: users can only see and change their own chats, and can only add messages to a chat they own. Messages have no user column; ownership is checked through the parent chat, so it lives in exactly one place.
- **FastAPI writes messages, and enforces ownership itself.** It uses a Supabase secret key, which bypasses RLS, so before doing anything else it checks that the chat belongs to the user it was given. It receives that user ID only from the SvelteKit server, which takes it from a verified session.
- **A stateless API process.** Conversation history is loaded from the database on every request, and a new chat engine is built per request. Nothing about a conversation lives in server memory, so concurrent users can't see each other's history and any number of instances could run side by side.
- **Ordering by identity, not timestamp.** The question and answer are inserted in one statement, so they share the same `created_at`. Messages are ordered by an identity `id` instead, which always increases in insertion order.
- **The document tables are closed to the API.** The vector and document-store tables have RLS enabled with no policies, so nothing can read them through Supabase's public API. FastAPI reads them over a direct database connection as the table owner.
- **Profiles follow the auth users.** A trigger creates a profile when a user signs up, using the name from their Google account or signup form, and a cascading foreign key removes it when the user is deleted.

## Web app

- Sign-in with email and password (with email confirmation) or with Google
- Transactional email (confirmation, password reset) sent through Resend from a verified subdomain, with links that work on any device
- A sidebar of the user's chats, newest first; new chats start on the first question
- Deleting a chat removes its messages through a database cascade
- Assistant answers rendered as Markdown, with raw HTML disabled so model output can't inject scripts

## Corpus

25 fictional documents in three folders:

- **Financial (10):** income statement, annual budget, cash flow statement, balance sheet, vendor invoice, expense report, purchase request, payroll summary, investor update, internal audit report
- **HR (5):** employee handbook, performance improvement plan, job description, onboarding checklist, org structure and headcount
- **Legal (10):** software license, employment contract, NDA, data processing agreement, SLA, board resolution, office lease, IP assignment, legal notice, terms of service

## Evaluation

`evals.json` holds 15 questions, each with an expected answer and its source documents:

| Category | Count | What it tests |
| --- | --- | --- |
| Factual | 5 | Single-document lookups, 4 of them from tables |
| Cross-department | 4 | Answers that need documents from two departments |
| Semantic | 3 | Questions worded differently from the source text |
| Negative | 3 | Information that isn't in the corpus; the right answer is "not found" |

Retrieval scoring compares the document IDs of the retrieved chunks against each question's expected sources. Two of the negative questions have no source documents, so they are only scored at the answer level. Each retriever setup writes its per-question results to its own file (see [Results](#results)).

## Stack

**Retrieval and API:** LlamaIndex · markitdown · BAAI/bge-small-en-v1.5 · Groq (Qwen) for table summaries and answers · FastAPI · uv
**Data and auth:** Supabase (Postgres, pgvector, Auth with Google OAuth, row-level security) · Resend for auth email
**Web:** SvelteKit with Supabase SSR auth

## Running it

### Database
1. Create a Supabase project.
2. Run `supabase/schema.sql` in the SQL editor. It creates `chats`, `messages` and `profiles`, their RLS policies and the profile trigger.
3. Run ingestion (below), then enable RLS on the two tables it creates, `data_llamaindex` and `data_docstore`, with no policies.

### Backend
```bash
uv sync
```

Create a `.env` in the project root:

```
api_key=<your Groq API key>
db_pass=<your Supabase Postgres password>
SUPABASE_URL=<your Supabase project URL>
SERVICE_ROLE_KEY=<your Supabase secret key (sb_secret_...)>
```

Point the database host in `src/rag_v2/pipeline.py` at your own Supabase project. Ingestion and the retrieval eval live in `pipeline.py`:

```bash
uv run python src/rag_v2/pipeline.py
```

Start the API (interactive docs at `http://127.0.0.1:8000/docs`):

```bash
uv run fastapi dev src/rag_v2/api.py
```

### Web app
In the SvelteKit app's folder, set the public Supabase URL and publishable key, plus a private `FASTAPI_URL=http://127.0.0.1:8000`, then:

```bash
npm install
npm run dev
```

For Google sign-in, add a Google OAuth client with `https://<project-ref>.supabase.co/auth/v1/callback` as its redirect URI, and enable the Google provider in Supabase. For email sign-up, configure custom SMTP and point the confirm-signup and reset-password templates at `/auth/confirm` with `token_hash` links.

## Known limitations

- **Small eval set.** With 13 retrieval-scored questions, each question moves the score by about 8 points.
- **Document-level scoring.** A question counts as a hit when any chunk from the right document is retrieved, even if it's the wrong section (see the G&A case above). Answer-level evaluation will close that gap.
- **Two-hop questions.** C1 asks who approved Tariq Al-Rashid's expense report and what that person's title is. The title is in the org structure document, but the manager's name only appears in the expense report, so a single retrieval pass has nothing to search for. The fix is multi-step retrieval: sub-questions, or a second retrieval using what the first one found.
- **Context noise.** Hybrid retrieval returns 6–9 chunks, and for single-document questions they often span 4–6 documents (the Q4 net income question pulls chunks from 6). Everything retrieved goes to the LLM.
- **Short memory.** Each answer sees only the last 10 messages of a chat.
- **No streaming or citations yet.** Answers arrive whole, and the sources behind them aren't shown.
- **Not hardened for public use.** The API trusts the user ID it receives, which is safe only while SvelteKit is its only caller; there is no rate limiting or CAPTCHA yet; and the Google OAuth app is in testing mode. See [Next](#next).
- **Heading-only chunks.** The table parser sometimes splits a section heading into its own tiny chunk, which can take a retrieval slot without carrying any content.
- **Low score separation.** bge-small gives very similar similarity scores to related chunks, which is why the G&A table ranked just outside the dense top 5.
- **Rate limits.** Table summarisation runs on Groq's free tier, so ingestion is throttled to stay under the tokens-per-minute limit.
- **Pinned dependency.** `llama-index-storage-docstore-postgres` is pinned to 0.5.0: version 0.6.0 passes an argument that the kvstore version it depends on doesn't accept.

## Next

- Reranker over the hybrid candidate set, to cut context noise, measured with the same eval
- Citations: show which documents each answer came from
- Streaming answers
- Before a public deployment: per-user rate limits and input limits, CAPTCHA on sign-up, a shared secret between the web app and the API, and publishing the Google OAuth app
- Answer-level evaluation: correctness, currency and units, and refusals
- Multi-step retrieval for two-hop questions
