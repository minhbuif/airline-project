"""Airline constraints must narrow by metadata without guessing ambiguous names."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.airline_search import airline_filter
from app.retriever import retrieve_reviews
from app.config import settings


class AirlineSearchTests(unittest.TestCase):
    def test_explicit_names_aliases_and_boundaries(self):
        values = airline_filter('How is QANTAS?').must[0].match.any
        self.assertIn('Qantas Airways', values)
        self.assertIn('qantas-airways', values)
        for query in ('American food', 'united crew', 'Emiratesville', 'Unknown Air',
                      'Which airlines except Emirates?', 'not Qatar Airways'):
            self.assertIsNone(airline_filter(query), query)

    def test_comparison_keeps_both_airlines(self):
        values = airline_filter('Qatar Airways versus Singapore Airlines').must[0].match.any
        self.assertIn('Qatar Airways', values)
        self.assertIn('Singapore Airlines', values)

    @patch('app.retriever.embed_text', return_value=[0.] * 384)
    @patch('app.retriever.QdrantClient')
    def test_constraint_sent_to_both_stores_without_unrelated_fallback(self, factory, embed):
        client = factory.return_value
        client.get_collections.return_value = SimpleNamespace(collections=[
            SimpleNamespace(name=settings.QDRANT_COLLECTION),
            SimpleNamespace(name=settings.QDRANT_WEB_COLLECTION)])
        client.query_points.return_value = SimpleNamespace(points=[])
        self.assertEqual(retrieve_reviews('Emirates crew'), [])
        self.assertEqual(client.query_points.call_count, 2)
        for call in client.query_points.call_args_list:
            self.assertIsNotNone(call.kwargs['query_filter'])
        client.close.assert_called_once()

    @patch('app.retriever.embed_text', return_value=[0.] * 384)
    @patch('app.retriever.QdrantClient')
    def test_evaluation_can_disable_constraints(self, factory, embed):
        client = factory.return_value
        client.get_collections.return_value = SimpleNamespace(collections=[SimpleNamespace(name=settings.QDRANT_COLLECTION)])
        client.query_points.return_value = SimpleNamespace(points=[])
        retrieve_reviews('Emirates crew', filter_airlines=False)
        self.assertIsNone(client.query_points.call_args.kwargs['query_filter'])


if __name__ == '__main__':
    unittest.main()
