from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

from backend.semantic_recommender import ARTIFACT_DIR, SemanticRecommender


class SemanticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Deliberately fail if real artifacts are absent; no fake vectors or downloads.
        cls.model = SemanticRecommender.load()

    def test_loading_uses_saved_embeddings_without_encoding(self):
        with patch.object(type(self.model.encoder), 'encode', side_effect=AssertionError('Recomputed embeddings')):
            restored = SemanticRecommender.load()
        np.testing.assert_array_equal(restored.embeddings, self.model.embeddings)
        self.assertEqual(restored.embeddings.shape, (69, 384))
        self.assertEqual(str(restored.encoder.device), 'cpu')

    def test_invalid_input(self):
        for text in ['', ' \t\n', None, 42]:
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.model.recommend(text)
        for top_k in [0, -1, True, 1.5]:
            with self.subTest(top_k=top_k), self.assertRaises(ValueError):
                self.model.recommend('mountains', top_k)

    def test_scores_ordering_and_real_metadata(self):
        for query in ['mountains hiking nature', 'history architecture culture']:
            results = self.model.recommend(query)
            self.assertEqual(len(results), 5)
            self.assertEqual(len({r['destination'] for r in results}), 5)
            scores = [r['similarity_score'] for r in results]
            self.assertEqual(scores, sorted(scores, reverse=True))
            self.assertTrue(all(-1 <= score <= 1 for score in scores))
            vector = self.model.encoder.encode([query], normalize_embeddings=True)
            expected = cosine_similarity(vector, self.model.embeddings).ravel()
            indices = np.argsort(-expected, kind='stable')[:5]
            np.testing.assert_allclose(scores, expected[indices], atol=1e-6)
            self.assertEqual([r['destination'] for r in results],
                             [self.model.destinations[i]['destination'] for i in indices])
            for row in results:
                self.assertIn({k: row[k] for k in ['destination', 'category', 'region']}, self.model.destinations)

    def test_query_encoding_only(self):
        with patch.object(self.model.encoder, 'encode', wraps=self.model.encoder.encode) as encode:
            self.model.recommend('lakes beautiful scenery')
        self.assertEqual(encode.call_count, 1)
        self.assertEqual(encode.call_args.args[0], ['lakes beautiful scenery'])

    def test_corrupt_embeddings_rejected_before_model_loading(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            (target / 'metadata.json').write_text((ARTIFACT_DIR / 'metadata.json').read_text(encoding='utf-8'), encoding='utf-8')
            (target / 'embeddings.npy').write_bytes(b'corrupted')
            with self.assertRaisesRegex(ValueError, 'checksum'):
                SemanticRecommender.load(target)


if __name__ == '__main__':
    unittest.main()
