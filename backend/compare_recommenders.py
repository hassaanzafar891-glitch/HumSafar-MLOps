"""Side-by-side examples, not a relevance evaluation."""
import json

from backend.recommender import DestinationRecommender, ROOT
from backend.semantic_recommender import SemanticRecommender

QUERIES = ['mountains hiking nature', 'history architecture culture',
           'lakes beautiful scenery', 'religious historical monuments']


def main():
    baseline, semantic = DestinationRecommender.load(), SemanticRecommender.load()
    comparisons = []
    lines = ['# TF-IDF and MiniLM example rankings', '',
             'Scores are cosine similarities, not probabilities. These examples do not establish model quality.', '']
    for query in QUERIES:
        left, right = baseline.recommend(query), semantic.recommend(query)
        comparisons.append({'preferences': query, 'tfidf': left, 'minilm': right})
        lines.extend([f'## {query}', '', '| Rank | TF-IDF destination (score) | MiniLM destination (score) |',
                      '|---|---|---|'])
        for rank, (a, b) in enumerate(zip(left, right), 1):
            lines.append(f"| {rank} | {a['destination']} ({a['similarity_score']:.4f}) | {b['destination']} ({b['similarity_score']:.4f}) |")
        lines.append('')
    target = ROOT / 'models/minilm'
    (target / 'comparison.json').write_text(json.dumps(comparisons, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    report = '\n'.join(lines)
    (target / 'comparison.md').write_text(report, encoding='utf-8')
    print(report)


if __name__ == '__main__':
    main()
