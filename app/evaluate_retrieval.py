"""Repeatable retrieval checks without Gemini calls or claims of answer accuracy."""

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import yaml

from app.retriever import retrieve_reviews
from app.dataset_io import airline_name


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--label', required=True, help='Output name, e.g. before or after.')
    parser.add_argument('--unfiltered', action='store_true', help='Baseline: disable airline-name filtering.')
    args = parser.parse_args()
    if not re.fullmatch(r'[a-zA-Z0-9_-]+', args.label):
        parser.error('Label must contain only letters, digits, underscores or hyphens.')
    path = Path('logs/evaluations') / (args.label + '.json')
    if path.exists():
        parser.error('Report already exists; choose a new label to preserve previous evidence.')
    cases = yaml.safe_load(Path('config/retrieval_checks.yaml').read_text())['cases']
    results = []
    for case in cases:
        question = f"What do passenger reviews say about {case['topic']} on {case['airline']}?"
        sources = retrieve_reviews(question, limit=5, filter_airlines=not args.unfiltered)
        matches = sum(airline_name(s.get('airline_name')).casefold() == case['airline'].casefold() for s in sources)
        results.append({'question': question, 'expected_airline': case['airline'],
                        'results': len(sources), 'matching_airline_results': matches,
                        'source_ids': [s.get('postgres_id') for s in sources],
                        'source_names': [s.get('source_name') for s in sources],
                        'evidence': [{k: s.get(k) for k in ('postgres_id', 'document_type', 'airline_name',
                                     'source_url', 'chunk_index', 'review_date', 'text', 'score')}
                                     for s in sources],
                        'human_evidence_relevance': None, 'human_citation_support': None})
    total = sum(r['results'] for r in results)
    report = {'created_at': datetime.now(timezone.utc).isoformat(), 'cases': results,
              'airline_filter_enabled': not args.unfiltered,
              'nonempty_questions': sum(bool(r['results']) for r in results),
              'airline_match_fraction': sum(r['matching_airline_results'] for r in results) / total if total else 0,
              'note': 'Airline-match proxy only. No answer-quality or citation-accuracy claim; manual assessment required.'}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2))
    print(f"{len(results)} questions: {report['nonempty_questions']} nonempty; airline match {report['airline_match_fraction']:.1%}. Saved {path}")


if __name__ == '__main__':
    main()
