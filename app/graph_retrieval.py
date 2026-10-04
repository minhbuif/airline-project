"""Read-only relationship selection for experimental graph-assisted RAG."""

from app.config import settings
from app.graph import get_graph_driver, graph_enabled
from app.logging_config import get_logger, tracked_operation

logger = get_logger(__name__)
MAX_GRAPH_CANDIDATES = 20_000

# Fixed Cypher: user input is always bound as parameters, never executable code.
REVIEW_CANDIDATES = '''
MATCH (r:DatasetReview)-[:ABOUT_AIRLINE]->(a:Airline)
WHERE ($airlines = [] OR a.name IN $airlines)
  AND ($route = '' OR EXISTS {
    MATCH (r)-[:FLOWN_ON_ROUTE]->(route:Route) WHERE route.name = $route
  })
  AND ($seat_type = '' OR EXISTS {
    MATCH (r)-[:IN_SEAT_TYPE]->(seat:SeatType) WHERE seat.name = $seat_type
  })
RETURN DISTINCT r.review_hash AS review_hash
LIMIT $limit
'''


def graph_review_hashes(airlines, route='', seat_type=''):
    """Return all eligible identities, or fail rather than silently truncate.

    Exact metadata matching intentionally mirrors the vector-filter baseline.
    The read transaction has a five-second server timeout; no graph writes occur.
    """
    if not graph_enabled():
        raise RuntimeError('Graph-assisted retrieval requires NEO4J_ENABLED=true.')
    if not airlines and not route and not seat_type:
        raise ValueError('Graph mode requires a recognized airline, route, or cabin filter.')
    from neo4j import Query
    try:
        with tracked_operation(logger, 'neo4j_retrieval_candidates'):
            rows, _, _ = get_graph_driver().execute_query(
                Query(REVIEW_CANDIDATES, timeout=5.0),
                parameters_={'airlines': airlines, 'route': route, 'seat_type': seat_type,
                             'limit': MAX_GRAPH_CANDIDATES + 1},
                database_=settings.NEO4J_DATABASE, routing_='r')
    except Exception as exc:
        raise RuntimeError('Graph-assisted retrieval failed. Check Neo4j or choose vector mode; no fallback was used.') from exc
    if len(rows) > MAX_GRAPH_CANDIDATES:
        raise ValueError('Graph candidate set is too broad; narrow the airline, route, or cabin.')
    hashes = [row['review_hash'] for row in rows]
    if any(not isinstance(value, str) or len(value) != 64 for value in hashes):
        raise RuntimeError('Graph contains invalid review identities; repair indexing before graph retrieval.')
    logger.info('event=graph_candidates_selected count=%s', len(hashes))
    return hashes
