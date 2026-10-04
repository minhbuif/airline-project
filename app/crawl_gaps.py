"""Plan bounded collection for review-coverage gaps; execute only on request."""

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from app.coverage import load_coverage
from app.dataset_io import airline_name
from app.crawl_sources import (CONFIG_PATH, OUTPUT_PATH, DEFAULT_MAX_PAGES,
                               crawl_sources, load_source_config, permitted_sources)


def plan_gaps(coverage, config, *, min_reviews=100, min_recent=10,
              max_airlines=3, pages_per_source=2, selected=()):
    """Use dataset counts as prioritization signals, not proof of web coverage.

    Aggregate case/slug variants. Do not guess subsidiary/brand aliases.
    Blocked candidates remain visible but do not consume runnable slots.
    """
    if min_reviews < 0 or min_recent < 0 or max_airlines < 1 or pages_per_source < 1:
        raise ValueError('Thresholds must be non-negative and crawl limits positive.')
    normalize_key = lambda value: airline_name(value).casefold()
    aliases = {normalize_key(alias): normalize_key(canonical)
               for canonical, names in config.get('coverage_aliases', {}).items()
               for alias in names}
    key = lambda value: aliases.get(normalize_key(value), normalize_key(value))
    counts = defaultdict(lambda: [0, 0])
    for row in coverage['airlines']:
        counts[key(row['Airline'])][0] += row['Reviews']
        counts[key(row['Airline'])][1] += row['Recent reviews (365 days)']
    selected = {key(name) for name in selected}
    configured = {key(name) for name in config['airlines']}
    unknown = selected - configured
    if unknown:
        raise ValueError('No configured sources for: ' + ', '.join(sorted(unknown)))
    allowed = permitted_sources(config)
    candidates = []
    for name, sources in config['airlines'].items():
        if selected and key(name) not in selected:
            continue
        total, recent = counts[key(name)]
        reasons = []
        if total < min_reviews:
            reasons.append(f'{total}/{min_reviews} total dataset reviews')
        if recent < min_recent:
            reasons.append(f'{recent}/{min_recent} dataset reviews in past 365 days')
        if not reasons:
            continue
        permitted = allowed.get(name, [])
        candidates.append({'airline': name, 'reviews': total, 'recent_reviews': recent,
                           'reasons': reasons,
                           'sources': [{'name': s['source_name'], 'url': s['url'],
                                        'permitted': s in permitted} for s in sources],
                           'max_scrape_calls': sum(1 + min(pages_per_source, max(1, int(s.get('max_pages', DEFAULT_MAX_PAGES))))
                                                   for s in permitted),
                           'status': 'pending' if permitted else 'blocked_permission'})
    candidates.sort(key=lambda row: (row['recent_reviews'], row['reviews'], row['airline']))
    runnable = 0
    for row in candidates:
        if row['status'] == 'pending':
            row['status'] = 'selected' if runnable < max_airlines else 'deferred_budget'
            runnable += 1
    return {'created_at': datetime.now(timezone.utc).isoformat(),
            'basis': 'Postgres dataset reviews only; web pages are not review counts. Recent deficits do not guarantee fresh crawl results.',
            'candidates': candidates,
            'unconfigured_gap_airlines': sorted(row['Airline'] for row in coverage['airlines']
                if not selected and key(row['Airline']) not in configured
                and (row['Reviews'] < min_reviews or row['Recent reviews (365 days)'] < min_recent)),
            'max_scrape_calls': sum(row['max_scrape_calls'] for row in candidates if row['status'] == 'selected')}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=CONFIG_PATH)
    parser.add_argument('--output', type=Path, default=OUTPUT_PATH)
    parser.add_argument('--airline', action='append', default=[])
    parser.add_argument('--min-reviews', type=int, default=100)
    parser.add_argument('--min-recent', type=int, default=10)
    parser.add_argument('--max-airlines', type=int, default=3)
    parser.add_argument('--pages-per-source', type=int, default=2)
    parser.add_argument('--topic-term', action='append', default=[], help='Accept pages containing any supplied phrase; repeat for synonyms.')
    parser.add_argument('--execute', action='store_true', help='Make paid scrape calls for permitted sources; otherwise preview only.')
    args = parser.parse_args(argv)
    # Validate budgets before database access.
    if min(args.min_reviews, args.min_recent) < 0 or min(args.max_airlines, args.pages_per_source) < 1:
        parser.error('Thresholds must be non-negative and limits positive.')
    plan = plan_gaps(load_coverage(), load_source_config(args.config),
                     min_reviews=args.min_reviews, min_recent=args.min_recent,
                     max_airlines=args.max_airlines, pages_per_source=args.pages_per_source,
                     selected=args.airline)
    plan['topic_terms'] = [term.strip() for term in args.topic_term if term.strip()]
    print(json.dumps(plan, indent=2))
    if not args.execute:
        print('Preview only: no scrape calls or output changes. Add --execute after reviewing permissions and budget.')
        return plan
    selected = [row['airline'] for row in plan['candidates'] if row['status'] == 'selected']
    if not selected:
        print('No runnable gaps. No scrape calls or output changes.')
        return plan
    plan['crawl_metrics'] = crawl_sources(config_path=args.config, output_path=args.output,
        selected_airlines=selected, append=True, max_pages_per_source=args.pages_per_source,
        topic_terms=plan['topic_terms'])
    print(json.dumps(plan['crawl_metrics'], indent=2))
    return plan


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError) as exc:
        raise SystemExit(f'Gap crawl failed: {exc}') from exc
