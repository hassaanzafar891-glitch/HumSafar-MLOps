# TF-IDF destination baseline

Run from `E:\GroupTravelMLOps` with the existing virtual environment:

```powershell
.venv/Scripts/python.exe -m backend.recommender fit
.venv/Scripts/python.exe -m backend.recommender demo
.venv/Scripts/python.exe -m backend.recommender recommend "mountains hiking nature"
.venv/Scripts/python.exe -m unittest discover -s tests -v
```

Fitting reads `data/processed/destinations_cleaned.csv` without modifying it.
`TfidfVectorizer` learns vocabulary and inverse document frequencies solely from
`recommendation_text`. It lowercases text, uses English stop words and unigram
tokens, and L2-normalizes vectors. No user ratings, labels, or supervised training
are involved. Default scikit-learn TF-IDF settings otherwise apply.

`models/tfidf_baseline.joblib` contains the fitted vectorizer, sparse destination
matrix, aligned destination/category/region metadata, dataset SHA-256, vocabulary
size, and scikit-learn version. Only load trusted artifacts. Refit explicitly
after dataset or scikit-learn version changes; inference never refits or silently
reloads a changed dataset.

For inference, import `DestinationRecommender` from `backend.recommender`, call
`DestinationRecommender.load()`, then `model.recommend(preferences, top_k=5)`.
The query uses the saved vocabulary and IDF weights; cosine similarity ranks
destination vectors. Results contain `destination` (source `_key`), `category`,
`region` (source `district`), and `similarity_score`. Scores lie in [0, 1] for
these nonnegative vectors and measure text overlap, not supervised probabilities
or measured recommendation quality. Stable ties retain source row order.

Blank/non-string preferences and invalid top_k raise ValueError. Queries with
no vocabulary overlap return an empty list. Otherwise the top five are returned
(or top_k, capped at the dataset size), including zero-score ties when there are
too few positive matches. Zero means no textual match; their source-order ranking
does not imply relevance.

Limitations: 69 destinations, uneven category coverage, English lexical matching
without stemming or semantic understanding (e.g. hiking and trekking differ),
and potentially dated/incomplete source descriptions. Region labels are broad,
and possible attraction aliases remain separate. No structured cost/budget,
travel-time, accessibility, seasonality, or safety constraints are modeled.
There are no genuine preference relevance labels, so accuracy, precision@k,
recall@k, and NDCG are not claimed. Unit tests verify implementation behavior,
not relevance. Group consensus, voting, APIs, and supervised models are outside
this baseline.
