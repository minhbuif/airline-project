"""Regression tests for additive ingestion, coverage, and source permissions."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import pandas as pd
from sqlalchemy import create_engine, text

from app.coverage import summarize_coverage
from app.crawl_sources import permitted_sources, crawl_sources
from app.dataset_io import content_key, discover_files, load_inputs, normalize
from app.dataset_store import persist_review
from app.ingest import parse_args, setup_qdrant_collection


class DatasetExpansionTests(unittest.TestCase):
    def test_source_aliases_dates_and_content_identity(self):
        item = normalize({'airline_name': 'qatar-airways', 'review_text': 'Helpful cabin crew. ' * 10,
                          'review_header': 'Good', 'over_all_rating': float('nan'), 'trip_verified': 'Yes'}, 2)
        self.assertEqual(item['airline_name'], 'Qatar Airways')
        self.assertEqual(item['title'], 'Good')
        self.assertEqual(item['verified'], 'Yes')
        self.assertEqual(item['review_date'], '')
        self.assertIsNone(item['overall_rating'])
        self.assertEqual(content_key(item), content_key({**item, 'country': 'Australia', 'review_date': '2020-01-01'}))
        self.assertNotEqual(content_key(item), content_key({**item, 'airline_name': 'Other Air'}))
        self.assertNotEqual(content_key({**item, 'review_text': 'Good', 'route': 'A to B'}),
                            content_key({**item, 'review_text': 'Good', 'route': 'A to C'}))

    def test_all_files_schema_and_pilot_source_rows(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ('a.csv', 'b.csv'):
                pd.DataFrame({'airline_name': ['A', 'A', 'B'], 'review_text': ['one', 'two', 'three']}).to_csv(root/name, index=False)
            paths = discover_files(root)
            self.assertEqual(len(paths), 2)
            result = load_inputs(paths, manifest_path=str(root/'none'), sample_per_airline=1)
            self.assertEqual(len(result), 4)
            self.assertEqual(result['_source_row'].tolist(), ['0', '2', '0', '2'])
            pd.DataFrame({'not_reviews': [1]}).to_csv(root/'bad.csv', index=False)
            with self.assertRaisesRegex(ValueError, 'missing airline_name'):
                load_inputs([root/'bad.csv'], manifest_path=str(root/'none'))

    def test_default_index_setup_never_deletes(self):
        client = Mock()
        from app.config import settings
        from app.embedder import VECTOR_SIZE
        client.get_collections.return_value.collections = [Mock(name='unused')]
        client.get_collections.return_value.collections[0].name = settings.QDRANT_COLLECTION
        client.get_collection.return_value.config.params.vectors.size = VECTOR_SIZE
        setup_qdrant_collection(client)
        client.delete_collection.assert_not_called()
        client.create_collection.assert_not_called()
        for argv in (['--replace'], ['--replace', '--confirm-replace', '--limit', '1']):
            with self.assertRaises(SystemExit):
                parse_args(argv)

    def test_repeat_and_cross_dataset_match_preserve_ids_and_metadata(self):
        engine = create_engine('sqlite://')
        item = normalize({'airline_name': 'Example Air', 'review_text': 'Very helpful crew and a comfortable seat. ' * 4,
                          'route': 'BNE to SIN'}, 0)
        item['review_summary'] = 'Helpful crew.'
        with engine.begin() as conn:
            cols = ', '.join(f'{field} TEXT' for field in (*item, 'review_hash', 'content_key'))
            conn.execute(text(f'CREATE TABLE airline_reviews (id INTEGER PRIMARY KEY, {cols})'))
            conn.execute(text('''CREATE TABLE review_sources (review_id INTEGER, file_sha256 TEXT, source_row_id TEXT,
                source_file TEXT, source_name TEXT, source_url TEXT, license TEXT, attribution TEXT,
                PRIMARY KEY(file_sha256, source_row_id))'''))
        source = dict(file_sha256='a', source_row_id='0', source_file='a.csv', source_name='A', source_url='', license='test', attribution='test')
        with patch('app.dataset_store.engine', engine):
            first, _, match = persist_review(item, source)
            self.assertFalse(match)
            again, _, match = persist_review(item, source)
            self.assertTrue(match)
            other, merged, match = persist_review({**item, 'route': '', 'country': 'Australia'},
                                                 {**source, 'file_sha256': 'b', 'source_name': 'B'})
        self.assertEqual((first, first), (again, other))
        self.assertEqual(merged['route'], 'BNE to SIN')
        self.assertEqual(merged['country'], 'Australia')
        self.assertEqual(len(merged['sources']), 2)
        with engine.connect() as conn:
            self.assertEqual(conn.execute(text('SELECT count(*) FROM airline_reviews')).scalar(), 1)
            self.assertEqual(conn.execute(text('SELECT count(*) FROM review_sources')).scalar(), 2)

    def test_coverage_unknown_and_future_dates(self):
        rows = [dict(airline_name='Example', review_date=value, date_flown='', seat_type='', route='')
                for value in ['2026-09-01', '', '2030-01-01', 'not a date']]
        result = summarize_coverage(rows, now='2026-10-01')[0]
        self.assertEqual(result['Recent reviews (365 days)'], 1)
        self.assertEqual(result['Missing/invalid review dates'], 3)

    def test_permission_gate_precedes_paid_api_calls(self):
        config = {'airlines': {'Example': [{'source_name': 'Provider'}]},
                  'provider_permissions': {'Provider': {'permission_confirmed': True}}}
        self.assertEqual(permitted_sources(config), {})
        config['provider_permissions']['Provider']['permission_reference'] = 'Consent ref 123'
        self.assertIn('Example', permitted_sources(config))
        with patch('app.crawl_sources.load_source_config', return_value={'airlines': config['airlines']}), patch('app.crawl_sources.Firecrawl') as client:
            with self.assertRaisesRegex(RuntimeError, 'No sources'):
                crawl_sources()
            client.assert_not_called()


if __name__ == '__main__':
    unittest.main()
