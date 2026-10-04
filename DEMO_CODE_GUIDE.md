# Airline Intelligence Assistant: Code Study Guide

This guide explains the project at code level so you can demonstrate both how
the product works and why it was designed this way.

## 1. The main idea

This project is a Retrieval-Augmented Generation application, usually called
RAG. It does not ask Gemini to answer from general memory alone. It first finds
relevant evidence from indexed airline reviews, places that evidence into the
prompt, and then asks Gemini to create a grounded answer.

The project has three main pipelines:

1. Dataset ingestion: spreadsheet to Postgres and Qdrant.
2. Web ingestion: airline websites to JSONL, Postgres, and Qdrant.
3. Question answering: user question to retrieval, Gemini, and a sourced answer.

```text
                         DATA PREPARATION

Spreadsheet ──→ ingest.py ───────→ Postgres: airline_reviews
                    │
                    ├────────────→ Qdrant: airline_reviews
                    └────────────→ Neo4j: review relationship graph


Websites ──→ crawl_sources.py ──→ crawled_pages.jsonl
                                      │
                                      ↓
                                ingest_web.py
                                      ├──→ Postgres: web_documents
                                      └──→ Qdrant: airline_web_documents


                         QUESTION ANSWERING

Streamlit or FastAPI
        ↓
      rag.py
        ↓
  retriever.py
        ↓
   embedder.py ──→ Qdrant similarity search
        ↓
Relevant dataset reviews and web chunks
        ↓
      rag.py builds a grounded prompt
        ↓
      llm.py calls Gemini
        ↓
Answer and supporting sources
```

Postgres and Qdrant have different responsibilities:

- Postgres stores complete, structured, durable records.
- Qdrant stores vectors and metadata for semantic similarity search.
- Gemini receives only the sources selected by the retrieval layer.

Neo4j complements both stores. It represents reviews as nodes connected to
airlines, routes, aircraft, countries, traveller types, and seat types. It is
used for relationship traversal and graph aggregates, not semantic ranking.

Gemini does not connect directly to Postgres or Qdrant.

## 2. Streamlit interface

File: `streamlit_app.py`

This is the interactive entry point used by the person asking questions.

### Page setup

`st.set_page_config()` configures the page title, icon, and wide layout. The
title and caption then explain that answers are grounded in project sources.

### Sidebar settings

The sidebar collects two values:

- `selected_airline`: the airline on which the question should focus.
- `top_k`: the maximum number of evidence sources to retrieve.

The selected airline is currently added to the semantic question:

```python
effective_question = (
    f"Focus only on {selected_airline}. "
    f"Question: {prompt}"
)
```

This is a prompt-based filter, not a strict Qdrant metadata filter. It usually
increases the relevance of the selected airline, but it does not guarantee that
every result belongs to that airline. A future improvement would add a Qdrant
payload condition such as `airline_name == selected_airline`.

### Streamlit session state

Streamlit reruns the complete script after each interaction. Chat history would
disappear without session state:

```python
if "messages" not in st.session_state:
    st.session_state.messages = []
```

Every user and assistant message is appended to this list. The application
replays the list after each rerun so the conversation remains visible.

### Logging session ID

One ID is generated for each browser session:

```python
if "_log_session_id" not in st.session_state:
    st.session_state._log_session_id = new_request_id("ui")
```

This connects all log messages from that browser session.

### Asking a question

The important application call is:

```python
result = answer_question(
    question=effective_question,
    limit=top_k,
)
```

Streamlit does not implement embeddings, database retrieval, or Gemini calls.
It delegates those responsibilities to the RAG layer. This keeps presentation
logic separate from business logic.

The returned dictionary has this general structure:

```python
{
    "question": "...",
    "answer": "...",
    "sources": [...],
}
```

The interface displays the answer, source metadata, similarity score, URL, and
a short evidence excerpt.

### Error handling

The main question operation is inside `try/except`. A Gemini, Qdrant, database,
embedding, or configuration failure therefore becomes a visible error message
instead of crashing the full Streamlit session.

## 3. RAG orchestration

File: `app/rag.py`

RAG means:

- Retrieval finds relevant evidence.
- Augmentation places that evidence into a prompt.
- Generation asks an LLM to answer from that evidence.

### `format_context()`

This function converts retrieved dictionaries into numbered source blocks.
Each block contains metadata such as source type, airline, URL, title, route,
seat type, aircraft, recommendation, and source text.

The source text is limited to 3,000 characters:

```python
review_text = review_text[:MAX_REVIEW_CHARACTERS]
```

This prevents one long review from taking most of the Gemini context window.
The blocks are separated with `---`, helping the model distinguish sources.

### `build_prompt()`

This function creates the final Gemini prompt. It instructs Gemini to:

- use only the supplied evidence;
- cite evidence using `[SOURCE 1]`, `[SOURCE 2]`, and so on;
- distinguish individual opinions from repeated patterns;
- treat reviews as subjective experiences;
- avoid unsupported safety, pricing, or schedule claims;
- admit when there is insufficient evidence;
- verify that comparisons contain sources for each airline.

This prompt is the primary grounding control. Citations are requested through
instructions, but the code does not yet programmatically validate every model
citation. Citation validation is a possible future improvement.

### `prepare_rag_input()`

This function validates the question and result limit. It rejects an empty
question, a non-integer limit, or a limit outside 1 through 10.

It then calls:

```python
reviews = retrieve_reviews(
    query=question,
    limit=limit,
)
```

After retrieval, it builds context and the model prompt. It returns both the
final prompt and intermediate data. This separation lets the `/search` API
endpoint retrieve evidence without paying for a Gemini call.

### `answer_question()`

This is the primary application orchestration function:

1. Validate and prepare the question.
2. Retrieve relevant evidence.
3. Return early if no evidence exists.
4. Send the grounded prompt to Gemini.
5. Number returned sources to match prompt citations.
6. Return the question, answer, and source dictionaries.

The syntax below adds a source number while copying the original dictionary:

```python
{
    "source_id": index,
    **review,
}
```

## 4. Semantic retrieval

File: `app/retriever.py`

This module searches both Qdrant collections and returns one consistent source
format to the rest of the application.

### Embedding the question

```python
query_vector = embed_text(query)
```

The question is converted into a 384-dimensional vector. Texts with similar
meaning should have vectors pointing in similar directions, even if they do not
use the same words.

For example, "uncomfortable economy seats" can match a review discussing poor
legroom without using exactly the same phrase.

### Discovering collections

The retriever asks Qdrant for the existing collection names. This lets search
continue when only the dataset collection or only the web collection exists.

The expected collections are:

- `airline_reviews`
- `airline_web_documents`

### `_query_collection()`

The Qdrant call is:

```python
client.query_points(
    collection_name=collection_name,
    query=query_vector,
    limit=limit,
    with_payload=True,
)
```

`with_payload=True` is important. The application needs source text and
metadata in addition to vector IDs and similarity scores.

### Retrieving extra candidates

The code retrieves at least ten candidates from each collection:

```python
per_collection_limit = max(limit * 2, 10)
```

The extra candidates allow dataset and web sources to compete in one global
ranking. Otherwise, one collection could dominate before their scores were
compared.

### `_normalize_point()`

Dataset reviews and web chunks have different payload fields. This function
adapts both formats into one contract containing fields such as:

```python
{
    "score": ...,
    "document_type": ...,
    "source_name": ...,
    "airline_name": ...,
    "text": ...,
}
```

The UI and RAG code therefore do not need separate handling for each storage
format.

### `_select_diverse_results()`

Candidates are sorted by descending score. A single web page can create many
chunks, so the code limits one web URL to two selected chunks:

```python
MAX_CHUNKS_PER_WEB_PAGE = 2
```

Without this rule, one long web page could occupy every result position.

### Current retrieval limitations

The retriever currently uses:

- vector similarity only;
- no keyword or hybrid search;
- no cross-encoder reranking;
- no minimum similarity threshold;
- no strict airline metadata filter.

These are reasonable project simplifications and useful future improvements.

## 5. Embeddings

File: `app/embedder.py`

### Model and vector size

```python
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
VECTOR_SIZE = 384
```

The embedding model converts text into 384 numbers. Qdrant collections must be
configured for exactly the same vector size.

### Lazy model loading

The global model begins as `None`:

```python
_model = None
```

`get_model()` loads it only when the first embedding is requested. Later calls
reuse the cached model. This avoids repeatedly loading an expensive model.

### Deferred dependency errors

The sentence-transformer import is wrapped in `try/except`. That lets other
parts of the application import even if the dependency is unavailable. A clear
runtime error is raised when an embedding is actually requested.

### Normalized vectors

```python
model.encode(text, normalize_embeddings=True)
```

Normalization makes every vector have unit length. This works naturally with
cosine similarity. The function also verifies that the result contains exactly
384 values, catching accidental model incompatibility.

## 6. Gemini integration

File: `app/llm.py`

### `get_client()`

This function verifies that:

1. The `google-genai` package imported successfully.
2. `GEMINI_API_KEY` is present.

It then creates a Gemini SDK client. Keeping this code isolated prevents
Gemini-specific details from spreading through the RAG and UI layers.

### `generate_answer()`

This function validates the prompt and sends it with:

```python
interaction = client.interactions.create(
    model=settings.GEMINI_MODEL,
    input=prompt,
)
```

It reads `interaction.output_text`, verifies that it is a non-empty string, and
returns a trimmed answer. SDK and network failures become application-level
`RuntimeError` exceptions that Streamlit and FastAPI can handle consistently.

## 7. Spreadsheet dataset ingestion

File: `app/ingest.py`

**Current ingestion path:** `main()` uses `app/dataset_io.py` to discover all
selected files, validate columns/checksums and normalize rows. It uses
`app/dataset_store.py` for cross-dataset matching, provenance, import history,
and a PostgreSQL advisory lock that serializes dataset import jobs.
The older single-file helpers described immediately below remain for
compatibility but are no longer called by `main()`.

### `find_dataset_file()`

This searches the configured landing directory for `.xlsx` and `.csv` files.
It returns the first matching file. One limitation is that multiple spreadsheet
files are not combined or selected interactively.

### `load_dataset()`

The extension controls which Pandas reader is used:

```python
pd.read_excel(file_path)
pd.read_csv(file_path)
```

Pandas loads the dataset into a `DataFrame`, an in-memory table.

### `clean_text()`

This normalizes spreadsheet cells by:

- converting null values to empty strings;
- removing line breaks;
- removing embedded verification labels;
- collapsing repeated whitespace;
- trimming leading and trailing whitespace.

Normalization improves both embedding quality and duplicate detection.

### `get_value()`

Source datasets may use different names for the same field. For example, an
airline may be stored under `NAMES`, `Airline Name`, `airline`, or
`airline_name`. `get_value()` returns the first populated alternative.

### `normalize_row()`

This maps a Pandas row into the application's standard schema. It creates fields
for airline, title, review text, country, dates, traveller type, seat type,
route, recommendation, aircraft, and rating.

Ratings are converted to `float` when possible. Invalid values become `None`,
which Postgres stores as `NULL`.

### `build_review_embedding_text()`

The structured metadata and review are combined into one embedding document:

```text
Airline: ...
Title: ...
Country: ...
...
Review:
...
```

This helper lives in `app/summarizer.py`. Embedding metadata together with the
review allows questions about route,
aircraft, seat type, or traveller type to match relevant records. The embedding
text now places a deterministic extractive review summary before the full
review, emphasizing representative details when the source review is long.

### Extractive review summaries

File: `app/summarizer.py`

`summarize_review()` splits a long review into sentences, removes repeated
sentences, scores the remaining sentences using informative word frequency and
a small position bonus, and selects up to three representative sentences. The
result is limited to 600 characters.

The summarizer is deliberately extractive rather than generative. It copies
sentences from the review instead of asking Gemini to rewrite them. This means
it adds no per-review API cost, cannot invent new claims, and produces the same
output on every ingestion run. Short reviews are preserved unchanged.

The summary is stored in Postgres and the Qdrant payload, used at the beginning
of the embedding input, and included separately in the grounded RAG context.
The full review remains available as the authoritative evidence.

### Duplicate-safe identity

Each normalized review receives a stable hash:

```python
item["review_hash"] = build_review_hash(item)
```

The current importer additionally matches a normalized content key through
`app/dataset_store.py`. Matches retain their stable review hash and gain source
provenance. They are re-embedded and upserted, so reruns repair incomplete indexes.

### Additive indexing and explicit replacement

The dataset Qdrant collection is preserved by default. Explicit replacement
requires `--replace --confirm-replace`, which also clears dataset Postgres rows
and the Neo4j dataset subgraph. The previous implementation always rebuilt it.
An explicit replacement also removes legacy vectors that were created before
deterministic identifiers were implemented. Web vectors are untouched.

The tradeoff is that an interrupted ingestion may leave the dataset collection
incomplete. Running the ingestion again repairs it.

### Row processing

For every valid, unique review, ingestion:

1. Calculates the stable review hash.
2. Produces a deterministic extractive summary.
3. Upserts the review and summary into Postgres.
4. Builds summary-first embedding text.
5. Creates a vector.
6. Builds the Qdrant metadata payload.
7. Creates a deterministic Qdrant point ID.
8. Adds the point to a pending batch.

### Batch writes

Qdrant points are written in batches of 100. Batch writes are substantially
faster than making one network request per review. `wait=True` asks Qdrant to
confirm the write before ingestion continues.

A Qdrant batch failure stops the run because continuing would create more
Postgres rows without matching searchable vectors. Other individual row errors
are counted and skipped.

## 8. Duplicate prevention details

File: `app/review_identity.py`

### Identity fields

The stable review identity includes every normalized review field except
`source_row_id`. Row numbers are excluded because they can change when a
spreadsheet is reordered.

### Canonical representation

Fields are always placed into the same ordered list. Nulls become empty strings,
the list is serialized into compact JSON, and SHA-256 hashes the bytes.

SHA-256 returns a 64-character hexadecimal value. Identical normalized records
therefore receive identical hashes.

### Deterministic UUID

The Qdrant point ID uses UUID version 5:

```python
uuid.uuid5(
    uuid.NAMESPACE_URL,
    f"airline-review:{review_hash}",
)
```

UUID version 5 always produces the same UUID for the same input. The earlier
`uuid4()` approach generated a different random ID on every run and therefore
created duplicate Qdrant points.

### Meaning of duplicate

Two reviews count as duplicates only when all normalized identity fields match.
If the review text, rating, date, or another identity field changes, the record
gets a new hash and is treated as different content.

## 9. Postgres persistence

File: `app/db.py`

### SQLAlchemy engine

```python
engine = create_engine(settings.postgres_url)
```

The engine is created once, while actual connections are opened lazily when a
database operation begins.

### Connection test

`test_postgres_connection()` executes `SELECT 1`. This verifies connectivity
without reading or modifying project records.

### Existing-database migration

`ensure_review_identity_schema()` supports databases created before duplicate
prevention was added. In one transaction, it:

1. Adds `review_hash` if necessary.
2. Checks whether its unique index exists.
3. Reads existing reviews.
4. Calculates their hashes.
5. Keeps the first occurrence of each hash.
6. Deletes later duplicates.
7. Stores hashes on surviving rows.
8. Makes the column non-null.
9. Creates a unique index.

`with engine.begin()` creates a transaction. A failure rolls back the migration
instead of leaving the schema half changed.

### Review upsert

`insert_review()` now uses:

```sql
ON CONFLICT (review_hash)
DO UPDATE SET ...
```

A new hash inserts a record. An existing hash updates the matching record. The
database unique index is essential because it also protects against two
application processes attempting the same insert concurrently.

`RETURNING id` gives ingestion the Postgres ID, which is stored in the Qdrant
payload for traceability.

## 10. Web crawling

File: `app/crawl_sources.py`

Configuration file: `config/airline_sources.yaml`

### Configuration-driven sources

The crawler does not hard-code source rules in Python. YAML defines each source's
listing URL, allowed URL pattern, page limit, minimum content length, required
terms, and pagination behavior. Airlines can therefore be added without
rewriting crawler logic.

### `canonicalize_url()`

This normalizes URLs by lowercasing scheme and hostname, removing default ports,
collapsing repeated path slashes, removing trailing slashes, and dropping query
strings and fragments. Normalization prevents tracking variants of one URL from
being stored as different pages.

### `extract_links()`

Links can come from Firecrawl's structured results, Markdown links, or bare URLs
in Markdown. They are converted into absolute canonical URLs and deduplicated.

### `quality_issue()`

This rejects pages that:

- contain bot-verification or CAPTCHA markers;
- are shorter than the configured minimum;
- do not contain required source terms;
- contain too little visible text after URLs are removed.

This stops verification screens, navigation shells, and off-topic pages from
becoming model evidence.

### `discover_target_urls()`

Only URLs matching each source's configured regular expression are accepted.
This controls both crawl scope and Firecrawl cost. Tripadvisor pagination URLs
can also be generated using the configured offset.

### `build_record()`

A successful page becomes a JSON-compatible dictionary containing airline,
source name, canonical URL, resolved URL, title, cleaned Markdown, content hash,
and UTC crawl timestamp.

### Deduplication

The crawler tracks both seen URLs and seen content hashes. URL deduplication
catches the same page identity; content deduplication catches different URLs
that return identical text.

### Atomic output

The complete result is written to a temporary JSONL file. `os.replace()` then
atomically replaces the final output. If a crawl fails before completion, the
previous good file is preserved.

## 11. Web ingestion

File: `app/ingest_web.py`

### JSONL input

JSONL means JSON Lines: every line is one independent JSON object. It is easy to
stream, and one malformed line can be skipped without invalidating the rest of
the file.

### Validation

`validate_record()` checks required fields, normalizes strings and timestamps,
and verifies that the SHA-256 content hash is 64 characters. Invalid lines are
reported and skipped.

### Postgres uniqueness

The web table has a unique key on `(source_url, content_hash)`. Reingesting the
same page content updates its row. Changed content has a new hash and can be
stored as another version unless ingestion uses `--replace`.

### Chunking

Long documents are split using:

```python
CHUNK_SIZE = 2500
CHUNK_OVERLAP = 300
```

Overlap preserves context around chunk boundaries. The splitter tries to end at
a sentence or word boundary instead of cutting text blindly.

### Embedding input

Each chunk is combined with airline, source, title, and URL metadata before it
is embedded. That improves retrieval for metadata-oriented questions.

### Deterministic IDs

Web vector IDs are based on `source_url + chunk_index`. Reingesting the same
page and chunk replaces the corresponding Qdrant point. The most predictable
refresh procedure is:

```bash
python -m app.ingest_web --replace
```

This removes old web rows and vectors before rebuilding them.

## 12. Neo4j graph storage

File: `app/graph.py`

Neo4j is an additional persistence and analytics layer. It does not replace
Postgres or Qdrant:

- Postgres remains the durable structured source of truth.
- Qdrant remains responsible for semantic vector similarity.
- Neo4j handles connected-data traversal and relationship aggregation.

### Graph model

Every dataset review is represented as a `Review` and `DatasetReview` node. Its
stable `review_hash` is the graph identity. Review nodes connect to dimension
nodes using these relationships:

```text
(DatasetReview)-[:ABOUT_AIRLINE]──────→(Airline)
(DatasetReview)-[:FROM_COUNTRY]───────→(Country)
(DatasetReview)-[:FLOWN_ON_ROUTE]─────→(Route)
(DatasetReview)-[:USED_AIRCRAFT]──────→(Aircraft)
(DatasetReview)-[:BY_TRAVELLER_TYPE]──→(TravellerType)
(DatasetReview)-[:IN_SEAT_TYPE]───────→(SeatType)
```

The review node also stores its Postgres ID, original text, extractive summary,
dates, recommendation, verification status, and overall rating.

### Optional integration

`NEO4J_ENABLED` controls whether graph storage is active. When it is false,
normal Postgres and Qdrant behavior continues without requiring Neo4j. This
keeps the graph layer optional for deployments that only need semantic search.

### Driver lifecycle

`get_graph_driver()` lazily creates and caches the official Neo4j Python driver.
It validates the configured password, and `test_graph_connection()` verifies
connectivity before ingestion resets any indexed data.

### Constraints and identity

`ensure_graph_schema()` creates uniqueness constraints for the review hash and
each dimension name. Neo4j backs uniqueness constraints with indexes, making
identity lookups faster while preventing concurrent duplicate nodes.

### Batch graph ingestion

`build_graph_record()` converts normalized review data into Neo4j-safe scalar
properties. `upsert_graph_reviews()` sends records in batches using Cypher's
`UNWIND` clause. `UNWIND` turns the parameter list into rows inside one query,
avoiding one network call per review.

Cypher `MERGE` finds or creates each review, dimension node, and relationship.
Since the identifying fields have uniqueness constraints, rerunning ingestion
does not create graph duplicates.

Empty optional dimensions are handled with `FOREACH` and `CASE`, because Neo4j
cannot `MERGE` a node using a null property.

### Snapshot synchronization

Dataset ingestion calls `reset_dataset_graph()` only in explicit replacement mode.
It deletes only `DatasetReview` nodes and orphaned dataset dimensions, preserving
unrelated graph data. This also removes stale reviews that disappeared from the
spreadsheet.

### Graph analytics

`get_airline_graph_overview()` starts from an `Airline` node and traverses its
connected reviews. It returns review count, average rating, recommendation
count, and the most common routes, aircraft, seat types, and traveller types.

FastAPI exposes this through:

```text
GET /graph/airlines/{airline_name}
```

Neo4j improves this type of relationship query, but it does not make vector
similarity inherently faster. Qdrant and Neo4j optimize different operations.

## 13. Logging and observability

File: `app/logging_config.py`

### Rotating logs

The project uses `RotatingFileHandler`. When the active file reaches its maximum
size, older logs are renamed `.1`, `.2`, and so on. This prevents unlimited log
growth.

### Correlation IDs

A `ContextVar` stores the current browser session, API request, crawl job, or
ingestion job ID. `RequestContextFilter` adds it to every related log record.

### Sensitive-data redaction

Fields with names containing markers such as `api_key`, `password`, `prompt`,
`question`, `review_text`, or `token` become `<redacted>`. Function arguments
and return values are not logged.

### `tracked_operation()`

This context manager records an operation's start, success or failure, duration,
and safe metadata:

```python
with tracked_operation(logger, "qdrant_collection_query"):
    ...
```

It re-raises failures after recording them, so logging never hides an error.

### `@track_call`

The decorator records the function, caller filename and line, duration, and
success or failure. `functools.wraps` preserves the original function metadata.
High-frequency calls use `@track_call_debug` so normal INFO logs remain useful.

## 14. FastAPI interface

File: `app/api.py`

### Pydantic validation

`AskRequest` requires a question between 3 and 1,000 characters and a limit
between 1 and 10. FastAPI rejects invalid request bodies before they reach RAG
logic.

### HTTP middleware

Middleware surrounds every request. It validates or generates an
`X-Request-ID`, records method and path, measures total duration, adds the ID to
the response, and records the response status.

The supplied request ID accepts only safe characters and a maximum length,
preventing multiline log injection.

### Endpoints

- `GET /health` confirms that the API process is running.
- `POST /search` retrieves evidence without calling Gemini.
- `POST /ask` performs retrieval and Gemini generation.

Errors map to meaningful HTTP responses:

- `400`: invalid user input.
- `502`: an upstream dependency such as Gemini or Qdrant failed.
- `500`: an unexpected application problem occurred.

## 15. Configuration

File: `app/config.py`

This module loads `.env` using `python-dotenv` and exposes one shared `settings`
object. Environment variables keep credentials and deployment-specific values
out of source code.

Local development uses hosts such as `localhost`. Docker containers use Compose
service names such as `postgres` and `qdrant`, which is why `.env` and
`.env.docker` contain different host values.

## 16. Supporting files

### `docker/init.sql`

Creates the initial `airline_reviews` table for a fresh Postgres volume. The
schema includes a unique `review_hash` constraint.

### `docker-compose.yml`

Defines Postgres, Qdrant, and an optional ingestion container. Named volumes
preserve Postgres and Qdrant data across container restarts.

### `Dockerfile`

Builds a Python 3.11 image, installs requirements, copies the application code,
and defaults to dataset ingestion.

### `requirements.txt`

Lists Python libraries for Pandas, Postgres, Qdrant, embeddings, Streamlit,
FastAPI, Gemini, Firecrawl, YAML, and related functionality.

### `.env.example`

Documents the required local environment variables without containing real
credentials.

### `.env.docker`

Contains container-specific service hosts and paths.

### `.gitignore`

Prevents credentials, datasets, logs, virtual environments, and generated
database storage from being committed.

### `app/search_test.py`

Runs Qdrant retrieval without Gemini. This proves that semantic search works
separately from generation.

### `app/__init__.py` and `tests/__init__.py`

Mark their directories as Python packages, enabling package-style imports.

## 17. Tests

The tests use small examples and mocks, so they do not call paid services.

- `tests/test_crawl_sources.py` verifies URL normalization, discovery, quality
  filtering, Markdown cleaning, source configuration, and atomic writing.
- `tests/test_retriever.py` verifies payload normalization, collection merging,
  ranking, and result diversity.
- `tests/test_logging_config.py` verifies redaction, request contexts, caller
  tracking, and that arguments are not recorded.
- `tests/test_review_identity.py` verifies stable hashes, independence from row
  order, content-change detection, and deterministic Qdrant IDs.
- `tests/test_summarizer.py` verifies extractive summaries, deterministic
  output, size limits, short-review preservation, and input validation.
- `tests/test_graph.py` verifies graph-record normalization, required identity
  checks, uniqueness constraints, batched `UNWIND`/`MERGE` writes, and airline
  analytics result handling without requiring a live Neo4j server.

These are primarily unit tests. They validate local deterministic logic but do
not replace live integration tests of Postgres, Qdrant, Neo4j, Firecrawl, and
Gemini.

Run them with:

```bash
python -m unittest discover -v
```

## 18. Design decisions to explain

### Why use Postgres, Qdrant, and Neo4j?

Postgres is the durable source of truth for structured records. Qdrant is
optimized for vector similarity search. Neo4j is optimized for traversing and
aggregating connections such as airline-to-route and review-to-aircraft. Each
database performs the job for which it is designed; Neo4j does not replace the
semantic ranking performed by Qdrant.

### Why not send all reviews to Gemini?

Sending everything would be slower, more expensive, and likely exceed the model
context limit. Retrieval chooses a small set of relevant evidence first.

### Why use a content hash instead of a spreadsheet row number?

Row numbers change when a spreadsheet is reordered. A normalized content hash
remains stable as long as the review itself is unchanged.

### Does Gemini train on this data?

No. The application retrieves sources at request time and includes them in the
prompt. This is RAG, not fine-tuning or model training.

### Are citations guaranteed?

The prompt requests numbered citations and source numbering is preserved, but
the application does not yet programmatically validate every citation.

### Is the airline selector strict?

No. It currently adds the airline to the semantic query. A strict Qdrant
metadata filter is a sensible future improvement.

### What happens if Qdrant or Neo4j is unavailable?

The retriever raises a contextual error. Streamlit displays it, FastAPI maps it
to an upstream-service response, and logging records the failure type. When
Neo4j is enabled, ingestion also fails clearly if its connectivity or write
checks fail so that the three stores do not silently drift apart.

### What is the main ingestion risk?

The three stores do not share one transaction. Default ingestion preserves
existing data, but new or enriched rows may be only partly indexed after an
interruption. Rerun the same files to repair writes. Explicit replacement clears
dataset data first and can leave an incomplete dataset until rerun.

### How are crawl quality and cost controlled?

Every source has an allowed URL pattern, maximum page count, delay, minimum
content length, and required terms. Verification pages and duplicates are
rejected.

## 19. Recommended presentation order

Use this sequence during the demonstration:

1. Show `streamlit_app.py` as the user entry point.
2. Follow `answer_question()` into `app/rag.py`.
3. Show `retrieve_reviews()` in `app/retriever.py`.
4. Explain vector creation in `app/embedder.py`.
5. Show the grounding rules in `build_prompt()`.
6. Show the Gemini call in `app/llm.py`.
7. Explain spreadsheet ingestion and content-hash deduplication.
8. Explain crawling, quality gates, and web chunking.
9. Show how Neo4j connects reviews to airlines, routes, and other dimensions.
10. Finish with logging and automated tests.

A concise closing explanation is:

> The application separates presentation, retrieval, generation, storage,
> ingestion, crawling, and observability into independent modules. Postgres
> preserves structured source records, Qdrant performs semantic retrieval,
> Neo4j supports relationship analytics, and Gemini generates answers only
> after relevant evidence is supplied. Stable content hashes prevent duplicate
> ingestion, and the logging layer tracks the workflow without storing prompts
> or credentials.

## 20. Demonstration commands

Start infrastructure:

```bash
docker compose up -d postgres qdrant neo4j
```

Prove retrieval works without Gemini:

```bash
python -m app.search_test
```

Start the complete user interface:

```bash
python -m streamlit run streamlit_app.py
```

Watch the execution flow in another terminal:

```bash
tail -f logs/airline_app.log
```

Run automated tests:

```bash
python -m unittest discover -v
```
