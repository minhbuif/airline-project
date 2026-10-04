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
Dataset spreadsheet ──→ ingest.py ──┬─→ Postgres airline_reviews
                                    ├─→ Qdrant airline_reviews
                                    └─→ Neo4j relationship graph

Web source pages ──→ ingest_web.py ─┬─→ Postgres web_documents
                                    └─→ Qdrant airline_web_documents

User question ──→ embedding ──→ combined Qdrant similarity search
                                      │
                                      ↓
                              evidence sent to Gemini
                                      │
                                      ↓
                               answer + sources
```

The original structured records are kept in Postgres. Their embedding vectors
are kept in Qdrant for semantic search. Neo4j stores dataset reviews as a graph
connected to airlines, routes, aircraft, countries, traveller types, and seat
types for fast relationship and aggregate queries.

## Quick start for an existing setup

If dependencies and data have already been installed, this is the normal way
to start the application:

```bash
cd /Users/minhbui/Documents/GitHub/airline-project
source .venv/bin/activate
docker compose up -d postgres qdrant neo4j
python -m streamlit run streamlit_app.py
```

Open `http://localhost:8501`. You do not need to crawl or ingest again every
time the application starts.

## Admin monitoring

The **Admin** page in Streamlit's sidebar shows recent logs, recorded tasks and
function calls, the active Gemini model, service configuration, and the exact
shared instructions used to build answers.

1. Add `ADMIN_PASSWORD=your-own-password` to your local `.env` file.
2. Restart Streamlit with `python -m streamlit run streamlit_app.py`.
3. Open **Admin** in the sidebar and sign in with that password.

The page refreshes every five seconds while open; you can disable this or
refresh manually. Filter logs by severity or search for an event, module,
caller, or request ID, then download the filtered view. Credentials are masked.
The page is disabled until an admin password is configured.

Monitoring is read-only. Change `GEMINI_MODEL` in `.env` and assistant
instructions in `app/prompts.py`, then restart the relevant processes.
Configuration reflects the Streamlit process; other processes may use different
environments. Instructions are prepended to the RAG input, not passed as a
separate Gemini system-message parameter.

Task activity is inferred from recorded start/completion/failure events, not a
job scheduler or process health check. An unmatched start does not prove a job
is still running. Only the configured current log is read (up to 1 MiB and
5,000 recent lines); rotated history is excluded. Log severity also depends on
`LOG_LEVEL`. Use HTTPS and deployment-level access control when exposing the
application outside local development.

## Requirements

Install these before starting:

- Python 3.11 or newer
- Docker Desktop or another Docker Compose installation
- Neo4j is supplied by Docker Compose; no separate installation is required
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

NEO4J_ENABLED=true
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=airline_graph_pass
NEO4J_DATABASE=neo4j

LANDING_PATH=./landing
```

Never commit `.env` or share real API keys. The file is ignored by Git.

### 5. Start Postgres, Qdrant, and Neo4j

Make sure Docker Desktop is running, then execute:

```bash
docker compose up -d postgres qdrant neo4j
docker compose ps
```

You should see `airline_postgres`, `airline_qdrant`, and `airline_neo4j`
running.

### 6. Ingest the spreadsheet dataset

Place `.xlsx` or `.csv` airline-review datasets in `landing/`. All matching files
are imported together by default. The original project dataset is:

```text
landing/Airline_Reviews_Combined.xlsx
```

Run ingestion:

```bash
python -m app.ingest
```

This loads structured reviews into Postgres, creates embeddings, and writes
them to the `airline_reviews` Qdrant collection. It is safe to run repeatedly:

- a deterministic extractive summary highlights representative sentences from
  each review without making an additional Gemini API call;
- the summary is placed before the full review when creating the embedding, so
  important themes remain prominent in long reviews;
- each normalized review receives a stable content hash;
- Postgres updates a matching review instead of inserting another row;
- the first run after this feature was added removes legacy Postgres
  duplicates;
- dataset vectors are upserted using stable IDs, preserving other imported files;
- when `NEO4J_ENABLED=true`, reviews are also batch-merged into a graph with
  index-backed unique identities and relationships to airlines, routes,
  aircraft, countries, traveller types, and seat types.

Default ingestion is additive. Crawled web documents are not affected. Provenance
is recorded per file checksum and original row number. Identical long review text
for the same airline matches even when metadata differs; existing nonempty
metadata is retained. Short generic comments use additional metadata to reduce
false matches. Legacy duplicate candidates are reported in Admin, not silently
removed by the new content-matching migration.

Validate or pilot a specific file:

```bash
python -m app.ingest --file landing/mendeley_skytrax_2026.xlsx --dry-run
python -m app.ingest --file landing/mendeley_skytrax_2026.xlsx --sample-per-airline 5
```

Repeat `--file` to select multiple inputs. `--limit N` reads the first N rows per
file; `--sample-per-airline N` selects the first N per airline, not a random or
statistically representative sample. Both preserve original row identifiers.
The selected file must still fit in memory. Add source names, URLs, checksums,
license and attribution to `config/dataset_sources.yaml`.

To intentionally replace **all dataset records across Postgres, Qdrant and
Neo4j** with the selected input files, use `--replace --confirm-replace`.
This is destructive and cannot be combined with a pilot row limit. Back up first.
Missing files are not deleted by default ingestion. The databases do not share
one transaction: rerun the same import after interruptions.

Admin → **Data coverage** → **Load data coverage** shows airline counts, date
coverage, missing cabin/route metadata, attribution, duplicate candidates and
recent import outcomes. It is a Postgres snapshot, not proof of index health.

Search now filters explicit airline names using `config/airline_aliases.yaml`.
The catalog covers 11 airlines; unknown names retain general semantic search.
Evaluation reports include source evidence for manual review and support an
`--unfiltered` baseline. Airline matching is not a measure of answer accuracy.

To preview targeted collection for low review counts or missing recent reviews,
run `python -m app.crawl_gaps`. Use `--airline`, `--min-reviews`, `--min-recent`,
and `--topic-term` to narrow the target. It makes no scrape calls unless
`--execute` is supplied and provider permission is recorded. Gap crawls append
to existing web output; ingest accepted pages with `python -m app.ingest_web`
without `--replace`. See the guide below for budgets and coverage limitations.

See [DATA_EXPANSION.md](DATA_EXPANSION.md) for the dataset audit, collection
permissions, evaluation commands, and remaining limitations.

The summary is extractive rather than generative: every summary sentence comes
from the original review. This keeps ingestion reproducible, avoids
hallucinated details, and adds very little runtime compared with embedding the
review itself.

### 7. Crawl web sources

The configured Flight-Report and Tripadvisor providers require prior consent
for automated collection. They are disabled through `provider_permissions` in
`config/airline_sources.yaml` until `permission_confirmed: true` and an actual
`permission_reference` are recorded. With no eligible source the crawler stops
before any paid API call and preserves existing output. The following crawl
commands apply only after that permission step.

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
docker compose up -d postgres qdrant neo4j
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
| `GET` | `/graph/airlines/{airline_name}` | Return Neo4j relationship statistics |
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

The tests do not call Firecrawl, Gemini, Postgres, Qdrant, or Neo4j.

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

### Neo4j

Open Neo4j Browser:

```text
http://localhost:7474
```

Sign in with the configured `NEO4J_USER` and `NEO4J_PASSWORD`. To visualize a
sample of the review graph, run:

```cypher
MATCH path=(review:DatasetReview)-[relationship]->(dimension)
RETURN path
LIMIT 50;
```

Query one airline's connected routes and review counts:

```cypher
MATCH (review:DatasetReview)-[:ABOUT_AIRLINE]->
      (:Airline {name: "Singapore Airlines"}),
      (review)-[:FLOWN_ON_ROUTE]->(route:Route)
RETURN route.name, count(review) AS reviews
ORDER BY reviews DESC
LIMIT 10;
```

The same graph analytics are available from FastAPI:

```bash
curl -s "http://127.0.0.1:8000/graph/airlines/Singapore%20Airlines"
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
│   ├── graph.py           Neo4j persistence and graph analytics
│   ├── ingest.py          Spreadsheet dataset ingestion
│   ├── ingest_web.py      Crawled web-document ingestion
│   ├── llm.py             Gemini client and answer generation
│   ├── logging_config.py  Rotating logs and safe call tracing
│   ├── rag.py             Prompt construction and RAG orchestration
│   ├── retriever.py       Combined Qdrant search
│   ├── review_identity.py Stable review hashes and vector IDs
│   ├── summarizer.py      Deterministic extractive review summaries
│   └── search_test.py     Command-line retrieval smoke test
├── config/
│   └── airline_sources.yaml
├── docker/
│   └── init.sql
├── landing/               Local datasets and crawl output
├── tests/                 Offline automated tests
├── .env.example           Safe environment-variable template
├── docker-compose.yml     Postgres, Qdrant, Neo4j, and ingestion services
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
| `NEO4J_ENABLED` | Enable graph storage and analytics | `true` |
| `NEO4J_URI` | Neo4j Bolt connection URI | `bolt://localhost:7687` |
| `NEO4J_USER` | Neo4j database user | `neo4j` |
| `NEO4J_PASSWORD` | Neo4j database password | `airline_graph_pass` |
| `NEO4J_DATABASE` | Neo4j logical database | `neo4j` |
| `LANDING_PATH` | Spreadsheet input directory | `./landing` |
| `LOG_LEVEL` | Log detail (`INFO` or `DEBUG`) | `INFO` |
| `LOG_FILE` | Rotating application log path | `logs/airline_app.log` |
| `LOG_MAX_BYTES` | Maximum size of each log file | `5242880` |
| `LOG_BACKUP_COUNT` | Number of rotated files to retain | `5` |

The `.env.docker` file uses Docker service names such as `postgres`, `qdrant`,
and `neo4j` instead of `localhost`.

## Application logs and call tracking

The application automatically records useful operational events in both the
terminal and a rotating log file:

```text
logs/airline_app.log
```

The logs show:

- incoming FastAPI requests, response status codes, and durations;
- application function calls and the filename and line that called them;
- Gemini, Firecrawl, Qdrant, Postgres, and Neo4j operations;
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
docker compose up -d postgres qdrant neo4j
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
docker compose up -d postgres qdrant neo4j
```

View status:

```bash
docker compose ps
```

Restart infrastructure:

```bash
docker compose restart postgres qdrant neo4j
```

Stop containers but keep stored data:

```bash
docker compose down
```

Delete containers and all Docker-managed Postgres, Qdrant, and Neo4j data:

```bash
docker compose down -v
```

> `docker compose down -v` is destructive. Use it only when you intentionally
> want a completely empty database and vector store.

## Current limitations

- Dataset ingestion adds/updates records by default. Only explicit replacement
  clears the dataset stores; replacement interruptions can leave partial indexes.
- Postgres, Qdrant, and Neo4j do not share one transaction. If ingestion is
  interrupted, rerun the same files to repair partial writes.
- Neo4j improves connected-data queries but does not replace Qdrant's semantic
  vector ranking; the two stores serve different query patterns.
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
docker compose up -d postgres qdrant neo4j
docker compose ps
python -m app.search_test
python -m streamlit run streamlit_app.py
```

Open Streamlit at `http://localhost:8501`, ask a passenger-experience question,
and expand **View supporting sources** under the answer.
