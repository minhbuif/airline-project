Project: Airline Review Intelligence Assistant

Current milestone:
- Docker Compose runs Postgres and Qdrant
- Dataset is stored in landing/
- Python ingestion script loads airline reviews
- Structured data is inserted into Postgres
- Embeddings are generated
- Vectors are inserted into Qdrant
- Semantic search test works

How to run:

## Open the project

```bash
cd /Users/minhbui/Documents/GitHub/airline-project
source .venv/bin/activate
```

---

## Start Postgres and Qdrant

```bash
docker compose up -d postgres qdrant
```

Show running services:

```bash
docker compose ps
```

Optional detailed check:

```bash
docker ps
```

---

## Show the project structure

```bash
find . -maxdepth 2 \
  -not -path "./.git*" \
  -not -path "./.venv*" \
  -not -path "./landing/*" \
  | sort
```

Main files to explain:

```text
app/config.py
app/db.py
app/embedder.py
app/ingest.py
app/search_test.py
docker/init.sql
Dockerfile
docker-compose.yml
requirements.txt
README.md
```

---

## Show ingestion logs

If the full dataset has already been ingested, show the previous output instead of running the full process again:

```bash
docker compose logs --tail=60 ingest
```

Expected information:

```text
Dataset file found
Loaded rows
Rows after duplicate removal
Inserted rows
Skipped rows
Ingestion completed
```

### Optional: run the ingestion container again

Only do this during the presentation if duplicate protection has been implemented:

```bash
docker compose up --build ingest
```

If ingestion is not idempotent yet, explain:

> Re-running the current prototype may create duplicate records. Deterministic IDs and upserts are planned for the next iteration.

---

## Verify data in Postgres

Open the Postgres command line:

```bash
docker exec -it airline_postgres \
  psql -U airline_user -d airline_rag
```

### Count all stored reviews

```sql
SELECT COUNT(*) AS total_reviews
FROM airline_reviews;
```

### Show five sample records

```sql
SELECT
    id,
    airline_name,
    title,
    seat_type,
    route,
    recommended
FROM airline_reviews
LIMIT 5;
```

### Show airlines with the most reviews

```sql
SELECT
    airline_name,
    COUNT(*) AS review_count
FROM airline_reviews
GROUP BY airline_name
ORDER BY review_count DESC
LIMIT 10;
```

### Show review count by cabin class

```sql
SELECT
    seat_type,
    COUNT(*) AS review_count
FROM airline_reviews
GROUP BY seat_type
ORDER BY review_count DESC;
```

Exit Postgres:

```sql
\q
```

---

## Verify the Qdrant vector database

Open the Qdrant dashboard:

```text
http://localhost:6333/dashboard
```

Show the collection:

```text
airline_reviews
```

### List collections from Terminal

```bash
curl -s http://localhost:6333/collections
```

### Count vector points exactly

```bash
curl -s -X POST \
  "http://localhost:6333/collections/airline_reviews/points/count" \
  -H "Content-Type: application/json" \
  -d '{"exact": true}'
```

Expected response format:

```json
{
  "result": {
    "count": 0
  },
  "status": "ok"
}
```

---

## Semantic search

Run the vector-search test:

```bash
python -m app.search_test
```

The test query in `app/search_test.py` should be similar to:

```text
What do passengers complain about in economy class?
```

Explain the flow:

```text
Question
→ embedding model
→ query vector
→ Qdrant similarity search
→ relevant passenger reviews
```

Key technical values:

```text
Embedding model: sentence-transformers/all-MiniLM-L6-v2
Vector size: 384
Distance metric: cosine similarity
```

---

## 9. Optional: demonstrate the RAG answer

This is an optional preview beyond the main Round 1 scope.

Make sure the Gemini key is available in `.env`:

```env
GEMINI_API_KEY=your_key
GEMINI_MODEL=gemini-2.5-flash
```

Never display or commit the real key.

Run a direct RAG test:

```bash
python -c "
from app.rag import answer_question

result = answer_question(
    'What do passengers praise about cabin crew?',
    limit=5
)

print('ANSWER:')
print(result['answer'])

print()
print('SOURCES:')

for index, source in enumerate(result['sources'], start=1):
    print()
    print(f'[SOURCE {index}]')
    print('Airline:', source.get('airline_name'))
    print('Title:', source.get('title'))
    print('Review date:', source.get('review_date'))
    print('Route:', source.get('route'))
    print('Seat type:', source.get('seat_type'))
    print('Recommended:', source.get('recommended'))
    print('Similarity score:', source.get('score'))
"
```

Explain:

> The answer is generated only after retrieving relevant passenger reviews from Qdrant. The source list is returned separately so each citation can be traced to the retrieved records.

---

## 10. Optional: run the FastAPI backend

Start the API:

```bash
python -m uvicorn app.api:app --reload
```

Open the interactive documentation:

```text
http://127.0.0.1:8000/docs
```

Recommended order:

1. Test `GET /health`
2. Test `POST /search`
3. Test `POST /ask`

Example request:

```json
{
  "question": "What are common passenger complaints about economy class?",
  "limit": 5
}
```

Stop Uvicorn:

```text
CTRL+C
```

---

## 11. Useful troubleshooting commands

### View Postgres logs

```bash
docker compose logs --tail=50 postgres
```

### View Qdrant logs

```bash
docker compose logs --tail=50 qdrant
```

### View ingestion logs

```bash
docker compose logs --tail=100 ingest
```

### Restart infrastructure

```bash
docker compose restart postgres qdrant
```

### Check Qdrant health

```bash
curl -s http://localhost:6333/healthz
```

### Check Python dependencies

```bash
python -m pip check
```

### Confirm the project virtual environment

```bash
which python
which pip
```

---

## 12. Stop services after the presentation

Stop containers while keeping database volumes:

```bash
docker compose down
```

Start them again later:

```bash
docker compose up -d postgres qdrant
```

Do not run the following unless you intentionally want to delete all database data:

```bash
docker compose down -v
```

---

# Recommended Presentation Sequence

Use this order for a short live demo:

```bash
cd /Users/minhbui/Documents/GitHub/airline-project
source .venv/bin/activate

docker compose up -d postgres qdrant
docker compose ps

docker compose logs --tail=40 ingest
```

Then verify Postgres:

```bash
docker exec -it airline_postgres \
  psql -U airline_user -d airline_rag
```

Run:

```sql
SELECT COUNT(*) AS total_reviews FROM airline_reviews;

SELECT
    airline_name,
    COUNT(*) AS review_count
FROM airline_reviews
GROUP BY airline_name
ORDER BY review_count DESC
LIMIT 10;

\q
```

Verify Qdrant:

```bash
curl -s -X POST \
  "http://localhost:6333/collections/airline_reviews/points/count" \
  -H "Content-Type: application/json" \
  -d '{"exact": true}'
```

Demonstrate retrieval:

```bash
python -m app.search_test
```

Optional RAG preview:

```bash
python -m uvicorn app.api:app --reload
```