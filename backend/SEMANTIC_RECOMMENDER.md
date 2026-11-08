# MiniLM semantic baseline

This uses the pretrained `sentence-transformers/all-MiniLM-L6-v2` on CPU.
No fine-tuning or supervised training occurs. The existing TF-IDF implementation
and artifact remain unchanged.

Install in the existing environment (CPU PyTorch first):

```powershell
.venv/Scripts/python.exe -m pip install torch==2.6.0 --index-url https://download.pytorch.org/whl/cpu
.venv/Scripts/python.exe -m pip install -r backend/requirements-semantic.txt
.venv/Scripts/python.exe -m backend.semantic_recommender build
.venv/Scripts/python.exe -m backend.semantic_recommender recommend "mountains hiking nature"
.venv/Scripts/python.exe -m backend.compare_recommenders
.venv/Scripts/python.exe -m unittest discover -s tests -v
```

Only the build step needs network access initially. The Hugging Face cache is
under `models/hf_cache/`. The runtime artifacts are `models/minilm/encoder/`
(local pretrained encoder/tokenizer), `embeddings.npy` (69 by 384 normalized
float32 vectors), and `metadata.json` (aligned destination metadata, model
revision when available, package version, sequence limit, and dataset/embedding
checksums). Keep the entire runtime directory together. Rebuild explicitly if
the cleaned dataset changes; loading does not read or update that dataset.

Build encodes only the genuine `recommendation_text` column. Load checks the
saved matrix checksum, shape, finite values, and normalization, then loads the
local encoder with network access disabled. Inference encodes only the user's
query and computes cosine similarity against the saved matrix. In Python:

```python
from backend.semantic_recommender import SemanticRecommender
model = SemanticRecommender.load()
results = model.recommend("lakes beautiful scenery", top_k=5)
```

Each result includes destination (source `_key`), category, region (source
`district`), and similarity_score. Blank/non-string inputs and nonpositive or
noninteger top_k values raise ValueError. Top_k is capped at the number of
destinations. Stable score ties follow source row order. Semantic cosine scores
can range from -1 to 1; negative scores are not silently clamped to zero.

The comparison command saves side-by-side rankings to `comparison.md` and full
results (including categories and regions) to `comparison.json` in models/minilm.
Scores from the two representations are not calibrated against each other.
These are examples, not an evaluation: there are no genuine relevance labels,
and neither model is claimed to be more accurate. Cosine similarity is not a
prediction probability. This model has no cost, budget, real-time conditions,
or user-specific rating inputs. Source coverage and possible aliases remain
limitations. English semantic associations may introduce biases or irrelevant
matches. Long descriptions are truncated at the encoder's sequence limit.

References: [MiniLM model card](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2)
and [SentenceTransformer API](https://www.sbert.net/docs/package_reference/sentence_transformer/model.html).
