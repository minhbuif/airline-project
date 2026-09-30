# Graph Report - airline-project  (2026-09-30)

## Corpus Check
- Corpus is ~20,171 words - fits in a single context window. You may not need a graph.

## Summary
- 440 nodes · 875 edges · 21 communities (17 shown, 4 thin omitted)
- Extraction: approximately 99.54% EXTRACTED · 0.46% INFERRED · 0% AMBIGUOUS · INFERRED: 4 edges (avg confidence: 0.88)
- Token cost: host-agent input/output usage unavailable; cost.json uses zero placeholders. No external Gemini API call was made.

## Community Hubs (Navigation)
- Web Crawl Quality
- Documented Application Architecture
- Web Document Ingestion
- Admin Configuration Monitoring
- Retrieval and Evidence Formatting
- API and Answer Generation
- Neo4j Storage and Analytics
- Spreadsheet Review Ingestion
- Extractive Review Summaries
- Stable Review Identities
- User Requests and Correlation
- Graph Records and Tests
- Database Preflight and Tracing
- Embeddings and Call Instrumentation
- Logging Infrastructure
- Logging Privacy Tests
- Dataset Vector Writes
- Logging Setup
- Log Metadata Redaction

## God Nodes (most connected - your core abstractions)
1. `tracked_operation()` - 41 edges
2. `track_call()` - 31 edges
3. `main()` - 27 edges
4. `get_logger()` - 19 edges
5. `main()` - 17 edges
6. `crawl_sources()` - 14 edges
7. `retrieve_reviews()` - 14 edges
8. `new_request_id()` - 13 edges
9. `set_request_id()` - 13 edges
10. `graph_enabled()` - 12 edges

## Surprising Connections (you probably didn't know these)
- `all-MiniLM-L6-v2 embeddings` --references--> `sentence-transformers library`  [EXTRACTED]
  DEMO_CODE_GUIDE.md → requirements.txt
- `monitor()` --calls--> `read_logs()`  [EXTRACTED]
  pages/1_Admin.py → app/admin.py
- `monitor()` --calls--> `task_activity()`  [EXTRACTED]
  pages/1_Admin.py → app/admin.py
- `monitor()` --calls--> `visible_config()`  [EXTRACTED]
  pages/1_Admin.py → app/admin.py
- `main()` --uses--> `GraphUpsertError`  [INFERRED]
  app/ingest.py → app/graph.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Stable review identity across persistence layers** — demo_code_guide_sha256, demo_code_guide_uuid5, demo_code_guide_postgres_upsert, demo_code_guide_dataset_review_graph [EXTRACTED 1.00]
- **Admin configuration and activity monitoring** — readme_admin, readme_model_config, readme_shared_instructions, readme_task_activity, readme_current_log [EXTRACTED 1.00]
- **Dataset ingestion across three stores** — demo_code_guide_dataset_ingestion, readme_postgres, readme_qdrant, readme_neo4j [EXTRACTED 1.00]

## Communities (21 total, 4 thin omitted)

### Community 0 - "Web Crawl Quality"
Cohesion: 0.07
Nodes (15): build_record(), canonicalize_url(), clean_markdown(), content_hash(), crawl_sources(), discover_target_urls(), extract_links(), get_metadata_value() (+7 more)

### Community 1 - "Documented Application Architecture"
Cohesion: 0.06
Nodes (47): Flight-Report passenger reports, Configured crawl quality rules, Airline source configuration, Tripadvisor passenger reviews, Atomic crawled_pages.jsonl output, ContextVar correlation IDs, Quality-filtered web crawling, Spreadsheet dataset ingestion (+39 more)

### Community 2 - "Web Document Ingestion"
Cohesion: 0.07
Nodes (15): build_embedding_text(), chunk_text(), clean_string(), create_qdrant_client(), deterministic_point_id(), ensure_qdrant_collection(), flush_points(), main() (+7 more)

### Community 3 - "Admin Configuration Monitoring"
Cohesion: 0.08
Nodes (10): check_password(), read_logs(), redact(), task_activity(), visible_config(), _get_bool(), _get_int(), Settings (+2 more)

### Community 4 - "Retrieval and Evidence Formatting"
Cohesion: 0.08
Nodes (8): format_context(), _normalize_point(), _query_collection(), retrieve_reviews(), _select_diverse_results(), build_review_embedding_text(), RetrieverTests, SummaryIntegrationTests

### Community 5 - "API and Answer Generation"
Cohesion: 0.08
Nodes (9): ask(), AskRequest, health(), search_only(), generate_answer(), get_client(), answer_question(), build_prompt() (+1 more)

### Community 6 - "Neo4j Storage and Analytics"
Cohesion: 0.15
Nodes (7): graph_airline_overview(), get_airline_graph_overview(), get_graph_driver(), graph_enabled(), GraphUpsertError, reset_dataset_graph(), upsert_graph_reviews()

### Community 7 - "Spreadsheet Review Ingestion"
Cohesion: 0.13
Nodes (8): insert_review(), close_graph_driver(), clean_text(), find_dataset_file(), get_value(), load_dataset(), main(), normalize_row()

### Community 8 - "Extractive Review Summaries"
Cohesion: 0.13
Nodes (4): _content_words(), summarize_review(), _truncate_at_word(), SummarizerTests

### Community 9 - "Stable Review Identities"
Cohesion: 0.15
Nodes (3): build_review_hash(), deterministic_review_point_id(), ReviewIdentityTests

### Community 10 - "User Requests and Correlation"
Cohesion: 0.15
Nodes (4): log_http_request(), new_request_id(), set_request_id(), search()

### Community 11 - "Graph Records and Tests"
Cohesion: 0.16
Nodes (3): build_graph_record(), FakeRecord, GraphTests

### Community 12 - "Database Preflight and Tracing"
Cohesion: 0.19
Nodes (7): ensure_review_identity_schema(), test_postgres_connection(), ensure_graph_schema(), test_graph_connection(), create_schema(), track_call(), tracked_operation()

### Community 13 - "Embeddings and Call Instrumentation"
Cohesion: 0.21
Nodes (4): embed_text(), get_model(), _decorate_call(), track_call_debug()

### Community 16 - "Dataset Vector Writes"
Cohesion: 0.22
Nodes (3): QdrantUpsertError, setup_qdrant_collection(), upsert_points()

### Community 17 - "Logging Setup"
Cohesion: 0.33
Nodes (3): configure_logging(), get_logger(), _read_int()

### Community 18 - "Log Metadata Redaction"
Cohesion: 0.40
Nodes (3): wrapper(), format_fields(), _safe_value()

## Knowledge Gaps
- **12 isolated node(s):** `ADMIN_PASSWORD access gate`, `Web source diversity cap`, `Deterministic Qdrant UUID5`, `Dataset graph and vector snapshot rebuild`, `ContextVar correlation IDs` (+7 more)
  These have ≤1 connection - possible missing edges. (Counts symbols only; 201 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **4 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `tracked_operation()` connect `Database Preflight and Tracing` to `Web Crawl Quality`, `Web Document Ingestion`, `Retrieval and Evidence Formatting`, `API and Answer Generation`, `Neo4j Storage and Analytics`, `Spreadsheet Review Ingestion`, `Embeddings and Call Instrumentation`, `Logging Infrastructure`, `Dataset Vector Writes`, `Logging Setup`, `Log Metadata Redaction`?**
  _High betweenness centrality (0.135) - this node is a cross-community bridge._
- **Why does `track_call()` connect `Database Preflight and Tracing` to `Web Crawl Quality`, `Web Document Ingestion`, `Retrieval and Evidence Formatting`, `API and Answer Generation`, `Neo4j Storage and Analytics`, `Spreadsheet Review Ingestion`, `User Requests and Correlation`, `Embeddings and Call Instrumentation`, `Logging Infrastructure`, `Logging Privacy Tests`, `Dataset Vector Writes`?**
  _High betweenness centrality (0.075) - this node is a cross-community bridge._
- **Why does `main()` connect `Spreadsheet Review Ingestion` to `Retrieval and Evidence Formatting`, `Neo4j Storage and Analytics`, `Extractive Review Summaries`, `Stable Review Identities`, `User Requests and Correlation`, `Graph Records and Tests`, `Database Preflight and Tracing`, `Embeddings and Call Instrumentation`, `Dataset Vector Writes`?**
  _High betweenness centrality (0.037) - this node is a cross-community bridge._
- **What connects `ADMIN_PASSWORD access gate`, `Web source diversity cap`, `Deterministic Qdrant UUID5` to the rest of the system?**
  _12 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Web Crawl Quality` be split into smaller, more focused modules?**
  _Cohesion score 0.07346938775510205 - nodes in this community are weakly interconnected._
- **Should `Documented Application Architecture` be split into smaller, more focused modules?**
  _Cohesion score 0.06105457909343201 - nodes in this community are weakly interconnected._
- **Should `Web Document Ingestion` be split into smaller, more focused modules?**
  _Cohesion score 0.0707070707070707 - nodes in this community are weakly interconnected._
## Extraction limitations and accounting

- Host-agent semantic token usage is unavailable from the orchestration tool. Reported zero token counters are placeholders, not a claim of zero token consumption. No external Gemini API was called.
- `.env.docker` was excluded as sensitive.
- `landing/Airline_Reviews_Combined.xlsx` was not converted because the optional Office converter is unavailable.
- `docker/init.sql` did not contribute AST entities because `tree_sitter_sql` is unavailable; documented database concepts are still represented.
- This is an undirected architecture map. Edge direction and repeated relations may be collapsed; see `health.json` for exact diagnostics.
- Semantic relationships reflect documentation and may describe intended rather than independently verified runtime behavior.

Graph health warning: 89 dangling-endpoint edges; 0 missing-endpoint edges; 0 self-loop edges; 16 same-endpoint edges collapsed in the undirected graph. The graph is usable but is not a complete call-graph proof.
