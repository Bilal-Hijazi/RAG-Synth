# RAG-Synth

Retrieval-augmented question answering over a synthetic enterprise corpus: 25 finance, HR and legal documents for a fictional Dubai SaaS company, Meridian Technologies Inc.

The focus is the part naive RAG gets wrong: **tables**. Budgets, income statements and invoices hold the figures people actually ask about, and plain vector search is bad at finding exact numbers inside them.

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
.docx files ──► markitdown ──► Markdown (tables preserved)
                                    │
               SimpleDirectoryReader (+ department metadata)
                                    │
               MarkdownElementNodeParser
               ├── text sections ──► text nodes
               └── tables ────────► LLM summary + full table
                                    │
               bge-small-en-v1.5 embeddings (local)
                                    │
     Supabase Postgres: pgvector table with a full-text column
                        + document store for upserts
                                    │
     Hybrid retrieval (vector + keyword) ──► LLM answer
                                    │
               FastAPI: POST /query, POST /chat
```

## API

| Endpoint | What it does |
| --- | --- |
| `POST /query` | Single question, single answer. Body: `{"question": "..."}` |
| `POST /chat` | Multi-turn chat. Follow-ups are rewritten into standalone questions before retrieval (LlamaIndex condense-plus-context). Body: `{"question": "..."}` |

Both return `{"response": "..."}`. Answers come back whole; streaming arrives with the web UI.

`/chat` currently keeps conversation memory inside the server process, so it is a single-user development scaffold. The next version is stateless: the client sends the conversation history with each request.

## Design decisions

- **Convert .docx to Markdown before loading.** The default .docx reader flattens tables into loose lines of text, so numbers lose their column headers. markitdown keeps them as proper Markdown tables.
- **Summarise tables, but keep the full table.** `MarkdownElementNodeParser` gives each table an LLM-written summary alongside the table itself. The summary describes what the table is about, which matches questions better than raw numbers; the table gives the model the actual figures.
- **One vector table, department as metadata.** Every document is tagged `legal`, `financial` or `hr` and stored together. Cross-department questions retrieve from everything at once, and filtering by department is still available. In production, access control would be row-level security on that column rather than separate tables.
- **Hybrid search.** Financial and legal questions hinge on exact terms ("G&A", "Q4 2024", "Series B") that embeddings blur. Postgres full-text search runs alongside vector search on the same table. In the eval it recovered a cross-department document that dense search missed at the same chunk count.
- **Idempotent ingestion.** A Postgres document store with stable file-based IDs (`filename_as_id`) and the `upserts` strategy means re-running ingestion skips unchanged files, instead of duplicating chunks and regenerating table summaries.
- **Stateless API, stateful app.** FastAPI only answers questions and never needs to know who the user is. The web app (SvelteKit) owns users and chat history in Supabase, protected by row-level security, and talks to FastAPI server-side, so the API is never exposed to the browser.

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

LlamaIndex · markitdown · BAAI/bge-small-en-v1.5 · Groq (Qwen) for table summaries and answers · Supabase Postgres with pgvector · FastAPI · uv

## Running it

```bash
uv sync
```

Create a `.env` in the project root:

```
api_key=<your Groq API key>
db_pass=<your Supabase Postgres password>
```

Point the database host in `src/rag_v2/pipeline.py` at your own Supabase project. Ingestion and the retrieval eval live in `pipeline.py`:

```bash
uv run python src/rag_v2/pipeline.py
```

Start the API, then try it from the interactive docs at `http://127.0.0.1:8000/docs`:

```bash
uv run fastapi dev src/rag_v2/api.py
```

## Known limitations

- **Small eval set.** With 13 retrieval-scored questions, each question moves the score by about 8 points.
- **Document-level scoring.** A question counts as a hit when any chunk from the right document is retrieved, even if it's the wrong section (see the G&A case above). Answer-level evaluation will close that gap.
- **Two-hop questions.** C1 asks who approved Tariq Al-Rashid's expense report and what that person's title is. The title is in the org structure document, but the manager's name only appears in the expense report, so a single retrieval pass has nothing to search for. The fix is multi-step retrieval: sub-questions, or a second retrieval using what the first one found.
- **Context noise.** Hybrid retrieval returns 6–9 chunks, and for single-document questions they often span 4–6 documents (the Q4 net income question pulls chunks from 6). Everything retrieved goes to the LLM.
- **Heading-only chunks.** The table parser sometimes splits a section heading into its own tiny chunk, which can take a retrieval slot without carrying any content.
- **Low score separation.** bge-small gives very similar similarity scores to related chunks, which is why the G&A table ranked just outside the dense top 5.
- **Single-user chat.** `/chat` keeps one conversation in server memory (see [API](#api)).
- **Rate limits.** Table summarisation runs on Groq's free tier, so ingestion is throttled to stay under the tokens-per-minute limit.
- **Pinned dependency.** `llama-index-storage-docstore-postgres` is pinned to 0.5.0: version 0.6.0 passes an argument that the kvstore version it depends on doesn't accept.

## Next

- Reranker (bge-reranker-v2-m3) over the hybrid candidate set, to cut context noise
- Answer-level evaluation: correctness, currency and units, and refusals
- Multi-step retrieval for two-hop questions
- Stateless `/chat` with client-supplied history, and sources in API responses
- Streaming, and the SvelteKit web app with Supabase auth (in progress)
