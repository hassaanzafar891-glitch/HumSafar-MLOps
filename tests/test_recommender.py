import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

from backend.recommender import DestinationRecommender


class RecommendationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = DestinationRecommender.fit()

    def test_valid_queries_return_five_genuine_destinations(self):
        genuine = {row['destination'] for row in self.model.destinations}
        for query in ['mountains hiking nature', 'history architecture culture']:
            results = self.model.recommend(query)
            self.assertEqual(len(results), 5)
            self.assertEqual(len({r['destination'] for r in results}), 5)
            for row in results:
                self.assertIn(row['destination'], genuine)
                self.assertTrue(row['category'])
                self.assertTrue(row['region'])

    def test_empty_or_invalid_preferences_rejected(self):
        for query in ['', ' \t\n', None, 123]:
            with self.subTest(query=query), self.assertRaises(ValueError):
                self.model.recommend(query)

    def test_order_and_scores_match_direct_cosine_computation(self):
        query = 'mountains hiking nature'
        results = self.model.recommend(query)
        scores = [row['similarity_score'] for row in results]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertTrue(all(0 <= score <= 1 for score in scores))
        expected = cosine_similarity(self.model.vectorizer.transform([query]), self.model.matrix).ravel()
        indices = np.argsort(-expected, kind='stable')[:5]
        self.assertEqual([r['destination'] for r in results],
                         [self.model.destinations[i]['destination'] for i in indices])
        np.testing.assert_allclose(scores, expected[indices])

    def test_no_vocabulary_overlap_returns_no_matches(self):
        self.assertEqual(self.model.recommend('zzzzqxxyy'), [])
        self.assertEqual(self.model.recommend('the and or'), [])

    def test_top_k_validation_and_limit(self):
        self.assertEqual(len(self.model.recommend('mountains', top_k=1)), 1)
        for top_k in [0, -1, True, 1.5]:
            with self.subTest(top_k=top_k), self.assertRaises(ValueError):
                self.model.recommend('mountains', top_k)
        self.assertLessEqual(len(self.model.recommend('mountains', 100)), len(self.model.destinations))

    def test_artifact_roundtrip_inference_does_not_refit(self):
        expected = self.model.recommend('history architecture culture')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'baseline.joblib'
            self.model.save(path)
            with patch('backend.recommender.TfidfVectorizer.fit_transform', side_effect=AssertionError('Unexpected refit')):
                restored = DestinationRecommender.load(path)
                self.assertEqual(restored.recommend('history architecture culture'), expected)
            self.assertEqual(restored.metadata, self.model.metadata)


if __name__ == '__main__':
    unittest.main()
