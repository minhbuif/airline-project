---
type: "query"
date: "2026-10-01T08:49:37.611336+00:00"
question: "Where should airline-aware retrieval be implemented?"
contributor: "graphify"
outcome: "useful"
source_nodes: ["retriever.py", "retrieve_reviews()"]
---

# Q: Where should airline-aware retrieval be implemented?

## Answer

Expanded graph vocabulary: retriever query airline filter sources. The existing graph points to app/retriever.py retrieve_reviews and _query_collection, plus tests/test_retriever.py and app/rag.py. Direct source inspection confirmed unconstrained combined vector search. Implemented configurable airline metadata constraints in app/airline_search.py and app/retriever.py, and evidence-bearing evaluation reports. The graph predates these changes and needs a future refresh.

## Outcome

- Signal: useful

## Source Nodes

- retriever.py
- retrieve_reviews()