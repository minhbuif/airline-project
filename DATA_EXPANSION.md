# Adding more airline data

The app can now import several review files without replacing its existing data. Start with a small pilot, inspect the results, and then import the full file.

## New dataset

The downloaded file is `landing/mendeley_skytrax_2026.xlsx`: **64,740 review rows covering 109 airline names**.

- Source: [Mendeley Data, version 1](https://data.mendeley.com/datasets/vgjk58vf8h/1), DOI `10.17632/vgjk58vf8h.1`.
- Attribution: Borse Rushikesh and Mishra Anirudh (2026). The publisher lists **CC BY 4.0**. Preserve the attribution and license when sharing derived data; this is not permission to scrape other websites.
- SHA-256: `30eab5be4c53b3cad8defa9ff49228caec0c1ec093aba0cc45a978aece2ca9d9`.
- The actual spreadsheet includes review dates and travel dates; 2,736 rows have no travel date. This differs from the page's description of removed journey dates.
- These are historical, self-selected passenger opinions, not a representative survey or current airline policies. Some overlap with the original dataset is expected.

Source details, checksums, licenses, and limitations are recorded in `config/dataset_sources.yaml`. Large downloaded files are ignored by Git; another computer will need its own copy.

## Run an import

From the project directory, activate the environment and start the databases:

```bash
source .venv/bin/activate
docker compose up -d postgres qdrant neo4j
```

Validate the new file without changing databases or calling APIs:

```bash
python -m app.ingest --file landing/mendeley_skytrax_2026.xlsx --dry-run
```

Try the first five reviews for each airline (a coverage pilot, **not a random or representative sample**):

```bash
python -m app.ingest --file landing/mendeley_skytrax_2026.xlsx --sample-per-airline 5
```

After reviewing the pilot, import the complete file:

```bash
python -m app.ingest --file landing/mendeley_skytrax_2026.xlsx
```

Running `python -m app.ingest` with no file arguments imports **all CSV and XLSX files in the landing folder**. Keep unrelated spreadsheets elsewhere. Repeating `--file` selects multiple files. `--limit 100` selects the first 100 rows per file instead of sampling by airline.

Summarization follows your configured settings. Gemini summarization can make paid API calls; the local summarizer does not. Embedding models may download on first use.

## What happens to duplicates?

The importer matches normalized airline names and review text. Very short comments also use title, date, and route to reduce accidental matches. Matching reviews keep their stable IDs and gain source provenance instead of another review row. Missing metadata can be filled without overwriting existing populated fields. This is exact normalized matching, **not fuzzy duplicate detection**; rewritten reviews and airline aliases can still require cleanup.

Each occurrence is tracked by file checksum and original row number. Repeating an import updates the same Postgres record, Qdrant point, and Neo4j review. It still recomputes summaries/embeddings and retries index writes, so repeating a run is not free. An advisory lock prevents two dataset importers running simultaneously.

The three databases are not one atomic transaction. If a run fails, inspect the logs and rerun the same inputs to repair incomplete indexing. Back up databases before major changes.

Only an explicit destructive rebuild removes existing dataset reviews:

```bash
python -m app.ingest --replace --confirm-replace
```

This replaces dataset reviews, vectors, and dataset graph records with the selected input files. Do not use it for ordinary additions. Limited pilots cannot use replacement mode. Web data has its own separate pipeline.

## Check coverage and search quality

Open **Admin → Data coverage** and load/refresh the snapshot. It shows review counts by airline, date coverage, missing routes/cabins, source attribution, duplicate-key warnings, and recent import runs. This is a Postgres snapshot, not proof that all three stores are synchronized, and excludes web chunks.

Use the same 30 questions before and after expansion:

```bash
python -m app.evaluate_retrieval --label before_expansion
# Run your import here.
python -m app.evaluate_retrieval --label after_expansion
```

Results are stored in `logs/evaluations/`. The automatic metric measures whether retrieved reviews have the expected airline name. It does **not** measure factual answer accuracy, topic relevance, or citation support. Inspect the returned review IDs and manually grade the evidence/citation fields before claiming that more data improved answers. This check does not generate Gemini answers.

## Why not simply crawl more sites?

The currently configured Flight-Report and Tripadvisor providers restrict automated collection without permission. Crawling is gated by `provider_permissions` in `config/airline_sources.yaml`: both `permission_confirmed: true` and a real `permission_reference` are required before a provider can run. Do not change these merely to bypass the check. No fresh crawl was performed for this expansion.

For the next expansion, prefer another explicitly licensed dataset or obtain provider permission. Official airline policy pages and government aviation statistics are useful future additions, but need separate document types, dates, attribution, and retrieval handling so policies and statistics are not confused with passenger opinions. They have not been imported here.

## Verification on 1 October 2026

- Reprocessed the original 7,730-row file: every row matched an existing review; no failures.
- The five-per-airline pilot selected 541 rows. Two lacked required content; 539 were processed, adding 466 reviews and matching 73 existing records.
- Repeating the same pilot matched all 539 valid rows, with no failures.
- The 30-question retrieval check returned results for every question both before and after. Airline-match fraction was unchanged at **76.7%**. This does not demonstrate an improvement in answer quality.
- Coverage flagged two existing duplicate-key candidates and 6,213 unattributed records. These were preserved for review, not automatically removed. The database already contained other data; its total is not the number added by this pilot.
- All 40 automated tests passed, as did Python compilation and Git whitespace checks.

The full new spreadsheet was downloaded and validated, but this continuation imported only the pilot. Use the full-file command above after inspecting its evidence quality.

## Next phase: airline-aware search

Search now recognizes explicit names from `config/airline_aliases.yaml` and applies
an airline metadata filter **before** vector ranking, in both dataset and web
collections. Recognized airlines with no evidence return no matches; the search
does not silently substitute other airlines.

The catalog covers 11 airlines. Add known payload spellings and aliases there as
coverage expands. Unknown names and general questions remain unfiltered; ambiguous
words such as “United” alone are deliberately not recognized. Exclusion wording
such as “except” or “not” disables automatic filtering. Comparisons match either
named airline but do not yet guarantee balanced evidence for both.

Compare the same index with and without filtering:

```bash
python -m app.evaluate_retrieval --label my_unfiltered_check --unfiltered
python -m app.evaluate_retrieval --label my_filtered_check
```

Use a new label each time: existing reports are protected from overwriting.
Reports now include retrieved text, dates, scores, and source identifiers for
manual evidence review. Treat these files as copies of the source material;
they are stored in the ignored logs folder. No Gemini answers or automatic
relevance judgments are generated.

On the same existing index, unfiltered search scored **76.7% airline matches**;
the filtered check achieved **100% airline matches**, with
results for all 30 questions. This is an expected effect of the constraint,
**not 100% answer accuracy**. Topic relevance and citation support still require
review. The regression suite now contains 44 passing tests.

This phase changes retrieval and evaluation only: it does not perform the full
dataset import, delete legacy duplicate candidates, or add policies/statistics.

## Targeted gap crawling

Preview airlines below 100 stored reviews **or** 10 dated reviews in the past
365 days (read-only Postgres access; no scraping or file writes):

```bash
python -m app.crawl_gaps --max-airlines 3 --pages-per-source 2
```

The plan shows counts, reasons, source URLs, permission blocks, deferred airlines,
and an upper bound on application scrape calls, including discovery pages. This
is not an exact Firecrawl credit estimate. Permission-blocked airlines do not use
the runnable airline budget. Airlines without configured sources are listed
separately. `coverage_aliases` in the source YAML merges explicitly known dataset
spellings for planning; it does not rewrite existing records.

For example, target a count/freshness gap for Qatar Airways and accept only pages
mentioning baggage or luggage:

```bash
python -m app.crawl_gaps --airline "Qatar Airways" --min-reviews 100 --min-recent 10 --topic-term baggage --topic-term luggage --pages-per-source 2
```

After reviewing the plan and recording actual provider consent, repeat with
`--execute`. A selected airline that meets both thresholds is not crawled.
No runnable gaps means no API calls, even with `--execute`. Existing provider
permission checks remain mandatory; both shipped providers are currently blocked.

Execution appends to `landing/web/crawled_pages.jsonl`, retaining URL/content
deduplication and quality gates. Existing pages are not refreshed. A no-new-pages
append leaves the file unchanged. Run only one crawl process per output file.
The planner limits attempts; rejected or duplicate pages are not automatically
replaced with extra paid requests beyond that budget.

After reviewing any collected pages, ingest them additively:

```bash
python -m app.ingest_web --input landing/web/crawled_pages.jsonl
```

Do **not** add `--replace` for a gap fill. Collection alone does not index data.
The gap signal counts dataset reviews only, not web pages/chunks, so a web crawl
will not close that numerical deficit on the next plan. Topic matching is a
case-insensitive phrase gate, not automated topic-gap measurement; fresh crawl
timestamps are not review dates. Inspect evidence before claiming a gap is filled.
