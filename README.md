# Airline Review Intelligence Assistant

An AI assistant that answers questions about passenger experiences using an
airline-review dataset and recently crawled web sources.

The application retrieves relevant evidence from Qdrant, sends that evidence
to Gemini, and returns an answer with the supporting sources. It includes a
Streamlit chat interface, a FastAPI backend, dataset ingestion, quality-filtered
web crawling, and automated tests.

## What you can ask

Examples:

- What do economy passengers complain about most?
- How do passengers describe Singapore Airlines cabin crew?
- Compare Qatar Airways and Emirates business-class experiences.
- What do recent web sources say about Lufthansa customer service?
- Which airlines receive positive comments about meals?

Answers are based only on indexed project sources. Passenger reviews and flight
reports are subjective experiences, not objective measures of airline quality
or safety.

## Supported airlines and web sources

The web crawler currently covers:

- Qatar Airways
- Emirates
- Singapore Airlines
- Cathay Pacific
- ANA
- Japan Airlines
- Turkish Airlines
- Lufthansa

Each airline uses two passenger-review sources:

- **Flight-Report** for detailed individual flight reports
- **Tripadvisor** for broader passenger feedback

Source URLs and crawl limits are configured in
[`config/airline_sources.yaml`](config/airline_sources.yaml).

## How the project works

```text
Dataset spreadsheet ──→ Postgres airline_reviews ──→ Qdrant airline_reviews
                                                       │
Web source pages ─────→ Postgres web_documents ─────→ Qdrant airline_web_documents
                                                       │
User question ────────→ embedding ─────────────────────┘
                                                       │
                                  combined similarity search
                                                       │
                                    evidence sent to Gemini
                                                       │
                                      answer + sources
```

The original structured records are kept in Postgres. Their embedding vectors
are kept in Qdrant for semantic search.

## Quick start for an existing setup

If dependencies and data have already been installed, this is the normal way
to start the application:

```bash
cd /Users/minhbui/Documents/GitHub/airline-project
source .venv/bin/activate
docker compose up -d postgres qdrant
python -m streamlit run streamlit_app.py
```

Open `http://localhost:8501`. You do not need to crawl or ingest again every
time the application starts.

## Requirements

Install these before starting:

- Python 3.11 or newer
- Docker Desktop or another Docker Compose installation
- A Gemini API key for generated answers
- A Firecrawl API key for collecting web sources

Firecrawl is only required when running the crawler. Gemini is only required
when generating an answer. Retrieval and automated tests can run without
calling Gemini.

## First-time setup

### 1. Open the project

```bash
cd /Users/minhbui/Documents/GitHub/airline-project
```

### 2. Create and activate a virtual environment

If `.venv` already exists, only run the activation command.

```bash
python3 -m venv .venv
source .venv/bin/activate
```

On Windows PowerShell, activation is:

```powershell
.venv\Scripts\Activate.ps1
```

Confirm that Python is coming from the project environment:

```bash
which python
```

The path should end with:

```text
airline-project/.venv/bin/python
```

### 3. Install dependencies

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 4. Create `.env`

If you do not already have a `.env` file:

```bash
cp .env.example .env
```

Add your keys and local Docker connection settings:

```env
GEMINI_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-2.5-flash

FIRECRAWL_API_KEY=your_firecrawl_api_key

POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=airline_rag
POSTGRES_USER=airline_user
POSTGRES_PASSWORD=airline_pass

QDRANT_HOST=localhost
QDRANT_PORT=6333
QDRANT_COLLECTION=airline_reviews
QDRANT_WEB_COLLECTION=airline_web_documents

LANDING_PATH=./landing
```

Never commit `.env` or share real API keys. The file is ignored by Git.

### 5. Start Postgres and Qdrant

Make sure Docker Desktop is running, then execute:

```bash
docker compose up -d postgres qdrant
docker compose ps
```

You should see `airline_postgres` and `airline_qdrant` running.

### 6. Ingest the spreadsheet dataset

Place a `.xlsx` or `.csv` airline-review dataset in `landing/`. The current
project uses:

```text
landing/Airline_Reviews_Combined.xlsx
```

Run ingestion:

```bash
python -m app.ingest
```

This loads structured reviews into Postgres, creates embeddings, and writes
them to the `airline_reviews` Qdrant collection.

> **Important:** dataset ingestion is not currently idempotent. Running it
> repeatedly can create duplicate Postgres rows and Qdrant points. Run it once
> for initial setup unless you have intentionally cleared the dataset storage.

### 7. Crawl web sources

For a low-cost smoke test that does not touch the project JSONL file:

```bash
python -m app.crawl_sources \
  --airline "Singapore Airlines" \
  --output /tmp/airline_crawl_test.jsonl
```

Run the complete crawl when the test looks healthy:

```bash
python -m app.crawl_sources
```

The full crawl can make approximately 56 bounded Firecrawl requests. Actual
credit usage depends on Firecrawl's current API behavior and your plan.

The crawler writes accepted pages to:

```text
landing/web/crawled_pages.jsonl
```

A normal crawl replaces this file atomically. Existing output remains untouched
if a selected airline produces no acceptable pages. Use `--append` only when
you intentionally want to retain existing valid records.

The crawler automatically:

- follows only configured review and report URL patterns;
- limits the number of pages collected from each source;
- strips image-only Markdown noise;
- rejects bot-verification and access-denied pages;
- rejects short or off-topic content;
- deduplicates canonical URLs and content hashes;
- prints accepted, rejected, duplicate, and failed-page counts.

### 8. Ingest the crawled web sources

For the first clean web ingestion—or after a fresh full crawl—run:

```bash
python -m app.ingest_web --replace
```

`--replace` deletes and rebuilds only:

- rows in the `web_documents` Postgres table;
- the `airline_web_documents` Qdrant collection.

It does not remove the original spreadsheet dataset, the `airline_reviews`
table, or the `airline_reviews` Qdrant collection.

### 9. Run the Streamlit application

```bash
python -m streamlit run streamlit_app.py
```

Open the URL printed by Streamlit, normally:

```text
http://localhost:8501
```

Use the sidebar to select an airline and choose how many sources to retrieve.

## Refreshing web content

To replace the previous crawl with current pages and rebuild the web index:

```bash
source .venv/bin/activate
docker compose up -d postgres qdrant
python -m app.crawl_sources
python -m app.ingest_web --replace
```

To add a selected airline crawl to the existing JSONL instead of replacing it:

```bash
python -m app.crawl_sources \
  --airline "ANA" \
  --append
```

Then ingest without clearing the web collection:

```bash
python -m app.ingest_web
```

For the most predictable results, prefer a complete crawl followed by
`app.ingest_web --replace`.

## Testing search without Gemini

Run the command-line retrieval test:

```bash
python -m app.search_test
```

Each result displays its similarity score and whether it came from a dataset
review or a crawled web page.

The search uses:

| Setting | Value |
| --- | --- |
| Embedding model | `sentence-transformers/all-MiniLM-L6-v2` |
| Vector size | `384` |
| Similarity metric | Cosine similarity |
| Dataset collection | `airline_reviews` |
| Web collection | `airline_web_documents` |

## Running the FastAPI backend

Start the API:

```bash
python -m uvicorn app.api:app --reload
```

Open the interactive API documentation:

```text
http://127.0.0.1:8000/docs
```

Available endpoints:

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Confirm the API process is running |
| `POST` | `/search` | Retrieve relevant sources without Gemini |
| `POST` | `/ask` | Retrieve sources and generate a Gemini answer |

Example request body:

```json
{
  "question": "What are common economy-class complaints?",
  "limit": 5
}
```

Stop Streamlit or Uvicorn with `Ctrl+C`.

## Running automated tests

The tests do not call Firecrawl, Gemini, Postgres, or Qdrant.

```bash
python -m unittest discover -v
```

Additional checks:

```bash
python -m compileall -q app tests streamlit_app.py
python -m pip check
```

## Checking stored data

### Postgres

Open the Postgres command line:

```bash
docker exec -it airline_postgres \
  psql -U airline_user -d airline_rag
```

Useful queries:

```sql
SELECT COUNT(*) AS dataset_reviews
FROM airline_reviews;

SELECT COUNT(*) AS web_documents
FROM web_documents;

SELECT airline_name, COUNT(*) AS review_count
FROM airline_reviews
GROUP BY airline_name
ORDER BY review_count DESC;

SELECT airline_name, source_name, COUNT(*) AS page_count
FROM web_documents
GROUP BY airline_name, source_name
ORDER BY airline_name, source_name;
```

Exit with:

```sql
\q
```

### Qdrant

Open the dashboard:

```text
http://localhost:6333/dashboard
```

List collections:

```bash
curl -s http://localhost:6333/collections
```

Count dataset vectors:

```bash
curl -s -X POST \
  "http://localhost:6333/collections/airline_reviews/points/count" \
  -H "Content-Type: application/json" \
  -d '{"exact": true}'
```

Count web vectors:

```bash
curl -s -X POST \
  "http://localhost:6333/collections/airline_web_documents/points/count" \
  -H "Content-Type: application/json" \
  -d '{"exact": true}'
```

## Project structure

```text
airline-project/
├── app/
│   ├── api.py             FastAPI endpoints
│   ├── config.py          Environment-based settings
│   ├── crawl_sources.py   Quality-filtered Firecrawl collection
│   ├── db.py              Postgres connection and review inserts
│   ├── embedder.py        Sentence-transformer embeddings
│   ├── ingest.py          Spreadsheet dataset ingestion
│   ├── ingest_web.py      Crawled web-document ingestion
│   ├── llm.py             Gemini client and answer generation
│   ├── logging_config.py  Rotating logs and safe call tracing
│   ├── rag.py             Prompt construction and RAG orchestration
│   ├── retriever.py       Combined Qdrant search
│   └── search_test.py     Command-line retrieval smoke test
├── config/
│   └── airline_sources.yaml
├── docker/
│   └── init.sql
├── landing/               Local datasets and crawl output
├── tests/                 Offline automated tests
├── .env.example           Safe environment-variable template
├── docker-compose.yml     Postgres, Qdrant, and ingestion services
├── Dockerfile
├── requirements.txt
└── streamlit_app.py       Streamlit entry point
```

## Environment variables

| Variable | Purpose | Typical local value |
| --- | --- | --- |
| `GEMINI_API_KEY` | Gemini authentication | Your secret key |
| `GEMINI_MODEL` | Gemini model name | `gemini-2.5-flash` |
| `FIRECRAWL_API_KEY` | Firecrawl authentication | Your secret key |
| `POSTGRES_HOST` | Postgres hostname | `localhost` |
| `POSTGRES_PORT` | Postgres port | `5432` |
| `POSTGRES_DB` | Database name | `airline_rag` |
| `POSTGRES_USER` | Database user | `airline_user` |
| `POSTGRES_PASSWORD` | Database password | `airline_pass` |
| `QDRANT_HOST` | Qdrant hostname | `localhost` |
| `QDRANT_PORT` | Qdrant HTTP port | `6333` |
| `QDRANT_COLLECTION` | Dataset vector collection | `airline_reviews` |
| `QDRANT_WEB_COLLECTION` | Web vector collection | `airline_web_documents` |
| `LANDING_PATH` | Spreadsheet input directory | `./landing` |
| `LOG_LEVEL` | Log detail (`INFO` or `DEBUG`) | `INFO` |
| `LOG_FILE` | Rotating application log path | `logs/airline_app.log` |
| `LOG_MAX_BYTES` | Maximum size of each log file | `5242880` |
| `LOG_BACKUP_COUNT` | Number of rotated files to retain | `5` |

The `.env.docker` file uses Docker service names such as `postgres` and
`qdrant` instead of `localhost`.

## Application logs and call tracking

The application automatically records useful operational events in both the
terminal and a rotating log file:

```text
logs/airline_app.log
```

The logs show:

- incoming FastAPI requests, response status codes, and durations;
- application function calls and the filename and line that called them;
- Gemini, Firecrawl, Qdrant, and Postgres operations;
- dataset, YAML, and JSONL file reads and writes;
- crawler and ingestion totals, failures, and timings;
- a `request_id` that connects all messages from one API request, Streamlit
  browser session, crawl, or ingestion job.

Follow the log while the application is running:

```bash
tail -f logs/airline_app.log
```

Find only calls, external operations, or HTTP requests:

```bash
rg 'event=(call|operation|http)_' logs/airline_app.log
```

At the default `INFO` level, repetitive per-review inserts and embeddings are
not logged individually. Use `LOG_LEVEL=DEBUG` temporarily when that detail is
needed. Logs rotate at 5 MB and keep five older files, such as
`airline_app.log.1`, so they cannot grow forever.

Prompts, review text, API keys, passwords, authorization headers, function
arguments, and function results are not logged. Keep the `logs/` directory
private anyway; it can still contain filenames, source URLs, airline names,
error types, and service metadata. The directory and `*.log` files are
ignored by Git.

## Common problems

### `ImportError: cannot import name 'genai' from 'google'`

The application is probably running with a different Python installation.
Activate `.venv` and launch Streamlit through that Python:

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run streamlit_app.py
```

Check the active executables:

```bash
which python
which streamlit
```

Both should point inside `.venv`.

### Cannot connect to Postgres or Qdrant

Start the services and inspect their status:

```bash
docker compose up -d postgres qdrant
docker compose ps
docker compose logs --tail=50 postgres
docker compose logs --tail=50 qdrant
```

Check Qdrant directly:

```bash
curl -s http://localhost:6333/healthz
```

### `GEMINI_API_KEY is missing`

Add the key to `.env`, save the file, and restart Streamlit or Uvicorn.

### `FIRECRAWL_API_KEY is missing`

Add the key to `.env` before running `python -m app.crawl_sources`.

### Crawl pages are rejected

The crawler intentionally rejects verification screens, very short pages,
off-topic pages, and responses missing expected review terms. Review the final
metrics and messages such as:

```text
rejected_blocked_or_verification_page
rejected_content_too_short
rejected_missing_required_terms
request_failed
```

Source rules can be adjusted in `config/airline_sources.yaml`. Keep page limits
small while testing to avoid unnecessary Firecrawl usage.

### No results from web sources

Confirm that the web crawl was ingested and both Qdrant collections exist:

```bash
python -m app.ingest_web --replace
curl -s http://localhost:6333/collections
python -m app.search_test
```

### The embedding model downloads slowly

The sentence-transformer model is downloaded and loaded the first time it is
used. Later runs reuse the local cache.

## Docker commands

Start infrastructure:

```bash
docker compose up -d postgres qdrant
```

View status:

```bash
docker compose ps
```

Restart infrastructure:

```bash
docker compose restart postgres qdrant
```

Stop containers but keep stored data:

```bash
docker compose down
```

Delete containers and all Docker-managed Postgres and Qdrant data:

```bash
docker compose down -v
```

> `docker compose down -v` is destructive. Use it only when you intentionally
> want a completely empty database and vector store.

## Current limitations

- Dataset ingestion can create duplicates when rerun.
- Web collection quality depends on third-party page availability and markup.
- Some sources may temporarily return bot-verification or access-denied pages.
- The crawler collects a bounded recent sample, not every historical review.
- Similarity scores measure textual relevance, not source truthfulness.
- The application does not provide aviation safety, live pricing, or schedule
  information.

## Quick demo checklist

For a short demonstration after data has already been ingested:

```bash
cd /Users/minhbui/Documents/GitHub/airline-project
source .venv/bin/activate
docker compose up -d postgres qdrant
docker compose ps
python -m app.search_test
python -m streamlit run streamlit_app.py
```

Open Streamlit at `http://localhost:8501`, ask a passenger-experience question,
and expand **View supporting sources** under the answer.
