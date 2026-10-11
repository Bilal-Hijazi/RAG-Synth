RAG-Synth

Retrieval-augmented question answering over a synthetic enterprise corpus: 25 finance, HR and legal documents for a fictional Dubai SaaS company, Meridian Technologies Inc.

The focus is the part naive RAG gets wrong: tables. Budgets, income statements and invoices hold the figures people actually ask about, and plain vector search is bad at finding exact numbers inside them.

Results

Retrieval evaluation on the 13 questions in evals.json that have source documents (hybrid retrieval, top-5):

Metric	Score
Strict hit rate (every expected source document retrieved)	69%
Mean source recall (share of expected source documents retrieved)	81%

Answer-level evaluation (correctness, and refusing questions the corpus can't answer) is next.

The case that shaped the design

"What is the FY2025 budget for G&A expenses?" (answer: AED 6,700,000, from a table in the FY2025 budget plan)

Dense retrieval only: five chunks from the right document came back, but they were the budget assumptions and section headings, not the expense table. The model correctly said it couldn't find the figure.
Hybrid retrieval (keyword + vector): the exact term "G&A" matched the table chunk, and the model answered AED 6,700,000.

The embedding similarity scores for those chunks all sat between 0.69 and 0.72. A small embedding model can't tell them apart, but keyword search can.

How it works
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
     Hybrid retrieval (vector + keyword) ──► LLM answer with sources
     
Design decisions
Convert .docx to Markdown before loading. The default .docx reader flattens tables into loose lines of text, so numbers lose their column headers. markitdown keeps them as proper Markdown tables.
Summarise tables, but keep the full table. MarkdownElementNodeParser gives each table an LLM-written summary alongside the table itself. The summary describes what the table is about, which matches questions better than raw numbers; the table gives the model the actual figures.
One vector table, department as metadata. Every document is tagged legal, financial or hr and stored together. Cross-department questions retrieve from everything at once, and filtering by department is still available. In production, access control would be row-level security on that column rather than separate tables.
Hybrid search. Financial questions hinge on exact terms ("G&A", "Q4 2024", invoice numbers) that embeddings blur. Postgres full-text search runs alongside vector search on the same table.
Idempotent ingestion. A Postgres document store with stable file-based IDs (filename_as_id) and the upserts strategy means re-running ingestion skips unchanged files, instead of duplicating chunks and regenerating table summaries.
Corpus

25 fictional documents in three folders:

Financial (10): income statement, annual budget, cash flow statement, balance sheet, vendor invoice, expense report, purchase request, payroll summary, investor update, internal audit report
HR (5): employee handbook, performance improvement plan, job description, onboarding checklist, org structure and headcount
Legal (10): software license, employment contract, NDA, data processing agreement, SLA, board resolution, office lease, IP assignment, legal notice, terms of service
Evaluation

evals.json holds 15 questions, each with an expected answer and its source documents:

Category	Count	What it tests
Factual	5	Single-document lookups, 4 of them from tables
Cross-department	4	Answers that need documents from two departments
Semantic	3	Questions worded differently from the source text
Negative	3	Information that isn't in the corpus; the right answer is "not found"

Retrieval scoring compares the document IDs of the retrieved chunks against each question's expected sources. Two of the negative questions have no source documents, so they are only scored at the answer level. Per-question results are in results.jsonl.

Stack

LlamaIndex · markitdown · BAAI/bge-small-en-v1.5 · Groq (Qwen) for table summaries and answers · Supabase Postgres with pgvector · uv

Running it
bash
uv sync

Create a .env in the project root:

api_key=<your Groq API key>
db_pass=<your Supabase Postgres password>

Point the database host in src/rag_v2/pipeline.py at your own Supabase project, then run ingestion and a test query:

bash
uv run python src/rag_v2/pipeline.py

Run the retrieval eval:
bash
uv run python src/rag_v2/<eval-script>.py

Known limitations
Small eval set. With 13 retrieval-scored questions, each question moves the score by about 8 points.
Heading-only chunks. The table parser sometimes splits a section heading into its own tiny chunk, which can take a retrieval slot without carrying any content.
Low score separation. bge-small gives very similar similarity scores to related chunks, which is why keyword search matters so much here.
Rate limits. Table summarisation runs on Groq's free tier, so ingestion is throttled to stay under the tokens-per-minute limit.
Pinned dependency. llama-index-storage-docstore-postgres is pinned to 0.5.0: version 0.6.0 passes an argument that the kvstore version it depends on doesn't accept.

Next
Reranker (bge-reranker-v2-m3) over a wider candidate set
Dense vs hybrid comparison across the full eval set
Answer-level evaluation: correctness and refusals
FastAPI endpoint with streaming, and a SvelteKit web app with Supabase auth (in progress)
