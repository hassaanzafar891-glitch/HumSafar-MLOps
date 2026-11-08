"""Pretrained MiniLM retrieval: build once, encode only queries at inference."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sentence_transformers import SentenceTransformer
import sentence_transformers
import torch
import transformers
from sklearn.metrics.pairwise import cosine_similarity

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = ROOT / 'models/minilm'
MODEL_ID = 'sentence-transformers/all-MiniLM-L6-v2'


class SemanticRecommender:
    def __init__(self, encoder, embeddings, metadata):
        self.encoder = encoder
        self.embeddings = embeddings
        self.metadata = metadata
        self.destinations = metadata['destinations']

    @classmethod
    def build(cls, dataset=ROOT / 'data/processed/destinations_cleaned.csv', artifact_dir=ARTIFACT_DIR):
        dataset, artifact_dir = Path(dataset), Path(artifact_dir)
        frame = pd.read_csv(dataset, keep_default_na=False, dtype=str)
        required = ['_key', 'category', 'district', 'recommendation_text']
        if frame.empty or not set(required).issubset(frame.columns):
            raise ValueError('Expected nonempty cleaned destination dataset')
        if any(frame[c].str.strip().eq('').any() for c in required) or frame['_key'].duplicated().any():
            raise ValueError('Blank fields or duplicate identifiers require review')
        encoder = SentenceTransformer(MODEL_ID, device='cpu', cache_folder=str(ROOT / 'models/hf_cache'))
        embeddings = encoder.encode(frame['recommendation_text'].tolist(), batch_size=16,
                                    normalize_embeddings=True, convert_to_numpy=True,
                                    show_progress_bar=False).astype(np.float32)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        encoder.save_pretrained(str(artifact_dir / 'encoder'))
        np.save(artifact_dir / 'embeddings.npy', embeddings, allow_pickle=False)
        metadata = {
            'format_version': 1, 'model_id': MODEL_ID,
            'model_revision': getattr(encoder[0].auto_model.config, '_commit_hash', None),
            'sentence_transformers_version': sentence_transformers.__version__,
            'torch_version': torch.__version__, 'transformers_version': transformers.__version__,
            'dataset_sha256': hashlib.sha256(dataset.read_bytes()).hexdigest(),
            'embeddings_sha256': hashlib.sha256((artifact_dir / 'embeddings.npy').read_bytes()).hexdigest(),
            'embedding_shape': list(embeddings.shape), 'normalized': True,
            'max_seq_length': encoder.max_seq_length,
            'destinations': frame[['_key', 'category', 'district']].rename(
                columns={'_key': 'destination', 'district': 'region'}).to_dict('records'),
        }
        (artifact_dir / 'metadata.json').write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        return cls(encoder, embeddings, metadata)

    @classmethod
    def load(cls, artifact_dir=ARTIFACT_DIR):
        artifact_dir = Path(artifact_dir)
        metadata = json.loads((artifact_dir / 'metadata.json').read_text(encoding='utf-8'))
        if metadata['format_version'] != 1 or metadata['model_id'] != MODEL_ID:
            raise ValueError('Unsupported semantic artifact')
        path = artifact_dir / 'embeddings.npy'
        if hashlib.sha256(path.read_bytes()).hexdigest() != metadata['embeddings_sha256']:
            raise ValueError('Embedding checksum mismatch')
        embeddings = np.load(path, allow_pickle=False)
        if (list(embeddings.shape) != metadata['embedding_shape']
                or embeddings.shape != (len(metadata['destinations']), 384)
                or not np.isfinite(embeddings).all()
                or not np.allclose(np.linalg.norm(embeddings, axis=1), 1, atol=1e-5)):
            raise ValueError('Invalid destination embeddings')
        encoder = SentenceTransformer(str(artifact_dir / 'encoder'), device='cpu', local_files_only=True)
        return cls(encoder, embeddings, metadata)

    def recommend(self, preferences, top_k=5):
        if not isinstance(preferences, str) or not preferences.strip():
            raise ValueError('Preferences must be a nonempty text string')
        if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < 1:
            raise ValueError('top_k must be a positive integer')
        query = self.encoder.encode([preferences.strip()], normalize_embeddings=True,
                                    convert_to_numpy=True, show_progress_bar=False)
        scores = np.clip(cosine_similarity(query, self.embeddings).ravel(), -1, 1)
        indices = np.argsort(-scores, kind='stable')[:top_k]
        return [dict(self.destinations[i], similarity_score=float(scores[i])) for i in indices]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['build', 'recommend'])
    parser.add_argument('preferences', nargs='?')
    args = parser.parse_args()
    if args.command == 'build':
        model = SemanticRecommender.build()
        print(json.dumps({k: v for k, v in model.metadata.items() if k != 'destinations'}, indent=2))
    else:
        if args.preferences is None:
            parser.error('recommend requires preferences')
        print(json.dumps(SemanticRecommender.load().recommend(args.preferences), indent=2))


if __name__ == '__main__':
    main()
