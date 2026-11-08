"""CPU-only content recommendation with reusable TF-IDF artifacts."""

import argparse
import hashlib
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / 'data/processed/destinations_cleaned.csv'
ARTIFACT = ROOT / 'models/tfidf_baseline.joblib'


class DestinationRecommender:
    def __init__(self, vectorizer, matrix, destinations, metadata):
        self.vectorizer = vectorizer
        self.matrix = matrix
        self.destinations = destinations
        self.metadata = metadata

    @classmethod
    def fit(cls, dataset_path=DATASET):
        path = Path(dataset_path)
        frame = pd.read_csv(path, keep_default_na=False)
        required = ['_key', 'category', 'district', 'recommendation_text']
        if not set(required).issubset(frame.columns) or frame.empty:
            raise ValueError('A nonempty cleaned destination dataset with recommendation_text is required')
        if any(frame[c].astype(str).str.strip().eq('').any() for c in required):
            raise ValueError('Required destination fields must not be blank')
        if frame['_key'].duplicated().any():
            raise ValueError('Destination identifiers must be unique')
        vectorizer = TfidfVectorizer(lowercase=True, stop_words='english', norm='l2')
        matrix = vectorizer.fit_transform(frame['recommendation_text'])
        destinations = frame[['_key', 'category', 'district']].rename(
            columns={'_key': 'destination', 'district': 'region'}
        ).to_dict(orient='records')
        metadata = {
            'format_version': 1,
            'sklearn_version': sklearn.__version__,
            'source_file': path.name,
            'source_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'destination_count': len(frame),
            'vocabulary_size': len(vectorizer.vocabulary_),
        }
        return cls(vectorizer, matrix, destinations, metadata)

    def recommend(self, preferences: str, top_k: int = 5) -> list[dict]:
        if not isinstance(preferences, str) or not preferences.strip():
            raise ValueError('Preferences must be a nonempty text string')
        if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < 1:
            raise ValueError('top_k must be a positive integer')
        query = self.vectorizer.transform([preferences])
        if query.nnz == 0:
            return []  # No shared vocabulary; avoid arbitrary zero-score suggestions.
        scores = np.clip(cosine_similarity(query, self.matrix).ravel(), 0.0, 1.0)
        # Stable ties follow source dataset order, including zero-score entries.
        indices = np.argsort(-scores, kind='stable')
        return [dict(self.destinations[i], similarity_score=float(scores[i]))
                for i in indices[:top_k]]

    def save(self, path=ARTIFACT):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({'vectorizer': self.vectorizer, 'matrix': self.matrix,
                     'destinations': self.destinations, 'metadata': self.metadata}, path, compress=3)

    @classmethod
    def load(cls, path=ARTIFACT):
        # Only load trusted local artifacts: joblib uses Python pickle internally.
        bundle = joblib.load(path)
        metadata = bundle['metadata']
        if metadata.get('format_version') != 1 or metadata.get('sklearn_version') != sklearn.__version__:
            raise ValueError('Artifact format or scikit-learn version differs; refit the baseline')
        return cls(bundle['vectorizer'], bundle['matrix'], bundle['destinations'], metadata)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest='command', required=True)
    fit_parser = subparsers.add_parser('fit', help='Fit on genuine cleaned descriptions and save artifacts')
    fit_parser.add_argument('--dataset', type=Path, default=DATASET)
    fit_parser.add_argument('--artifact', type=Path, default=ARTIFACT)
    recommend_parser = subparsers.add_parser('recommend', help='Load artifacts and rank without refitting')
    recommend_parser.add_argument('preferences')
    recommend_parser.add_argument('--top-k', type=int, default=5)
    recommend_parser.add_argument('--artifact', type=Path, default=ARTIFACT)
    demo_parser = subparsers.add_parser('demo', help='Run both sample queries without refitting')
    demo_parser.add_argument('--artifact', type=Path, default=ARTIFACT)
    args = parser.parse_args()
    try:
        if args.command == 'fit':
            model = DestinationRecommender.fit(args.dataset)
            model.save(args.artifact)
            print(json.dumps(model.metadata, indent=2))
        else:
            model = DestinationRecommender.load(args.artifact)
            queries = [args.preferences] if args.command == 'recommend' else [
                'mountains hiking nature', 'history architecture culture']
            for query in queries:
                print(json.dumps({'preferences': query, 'results': model.recommend(
                    query, args.top_k if args.command == 'recommend' else 5)}, indent=2, ensure_ascii=True))
    except (ValueError, OSError) as exc:
        parser.exit(1, f'Recommendation failed: {exc}\n')


if __name__ == '__main__':
    main()
