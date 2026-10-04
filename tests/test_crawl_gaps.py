"""Gap planning and bounded execution without network or database dependencies."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.crawl_gaps import main, plan_gaps
from app.crawl_sources import crawl_sources


def source():
    return dict(source_name='Approved', url='https://example.com/list',
                url_pattern=r'^https://example\.com/review/', max_pages=10,
                min_content_characters=10, required_terms=['Example'], request_delay_seconds=0)


def config():
    return {'airlines': {'Example': [source()], 'Blocked': [{**source(), 'source_name': 'Blocked'}]},
            'provider_permissions': {'Approved': {'permission_confirmed': True, 'permission_reference': 'test-consent'}}}


class GapCrawlTests(unittest.TestCase):
    def test_missing_airlines_permissions_and_budget(self):
        plan = plan_gaps({'airlines': []}, config(), max_airlines=1, pages_per_source=2)
        statuses = {row['airline']: row['status'] for row in plan['candidates']}
        self.assertEqual(statuses, {'Blocked': 'blocked_permission', 'Example': 'selected'})
        self.assertEqual(plan['max_scrape_calls'], 3)

    def test_sufficient_counts_and_slug_aggregation(self):
        cfg = {'airlines': {'Example Air': [source()]}, 'provider_permissions': config()['provider_permissions']}
        rows = [{'Airline': name, 'Reviews': 50, 'Recent reviews (365 days)': 5}
                for name in ['Example Air', 'example-air']]
        self.assertEqual(plan_gaps({'airlines': rows}, cfg)['candidates'], [])
        cfg['coverage_aliases'] = {'Example Air': ['Example Airways']}
        rows[1]['Airline'] = 'Example Airways'
        self.assertEqual(plan_gaps({'airlines': rows}, cfg)['candidates'], [])
        with self.assertRaises(ValueError):
            plan_gaps({'airlines': []}, cfg, selected=['Unknown'])
        with self.assertRaises(ValueError):
            plan_gaps({'airlines': []}, cfg, pages_per_source=0)

    @patch('app.crawl_gaps.crawl_sources')
    @patch('app.crawl_gaps.load_source_config', return_value=config())
    @patch('app.crawl_gaps.load_coverage', return_value={'airlines': []})
    def test_preview_and_execute_scope(self, coverage, load, crawl):
        main([])
        crawl.assert_not_called()
        crawl.return_value = {'pages_accepted': 1}
        main(['--execute', '--topic-term', 'baggage', '--pages-per-source', '1'])
        self.assertEqual(crawl.call_args.kwargs['selected_airlines'], ['Example'])
        self.assertTrue(crawl.call_args.kwargs['append'])
        self.assertEqual(crawl.call_args.kwargs['topic_terms'], ['baggage'])

    @patch('app.crawl_gaps.crawl_sources')
    @patch('app.crawl_gaps.load_source_config', return_value={'airlines': {'Blocked': [source()]}})
    @patch('app.crawl_gaps.load_coverage', return_value={'airlines': []})
    def test_blocked_execute_never_falls_back_to_all(self, coverage, load, crawl):
        main(['--execute'])
        crawl.assert_not_called()

    @patch('app.crawl_sources.settings')
    @patch('app.crawl_sources.Firecrawl')
    @patch('app.crawl_sources.load_source_config', return_value=config())
    def test_page_budget_topic_gate_and_existing_output(self, load, factory, settings):
        settings.FIRECRAWL_API_KEY = 'test'
        def scrape(url, **kwargs):
            if url.endswith('/list'):
                return SimpleNamespace(markdown='', links=[f'https://example.com/review/{i}' for i in range(10)])
            return SimpleNamespace(markdown=url + ' Example baggage arrived safely. ' * 20, metadata={})
        factory.return_value.scrape.side_effect = scrape
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'pages.jsonl'
            original = {'source_url': 'https://example.com/old', 'content_hash': 'old'}
            path.write_text(json.dumps(original) + '\n')
            result = crawl_sources(output_path=path, selected_airlines=['Example'], append=True,
                                   max_pages_per_source=1, topic_terms=['baggage'])
            self.assertEqual(factory.return_value.scrape.call_count, 2)
            self.assertEqual(result['pages_accepted'], 1)
            self.assertEqual(len(path.read_text().splitlines()), 2)
            before = path.read_bytes()
            result = crawl_sources(output_path=path, selected_airlines=['Example'], append=True,
                                   max_pages_per_source=2, topic_terms=['refund'])
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(result['records_written'], 0)
            self.assertEqual(result['rejected_off_topic'], 1)


if __name__ == '__main__':
    unittest.main()
