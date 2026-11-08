"""Audit genuine Hawaii gzip JSONL data with a temporary, disk-backed graph.

No extraction, model training, or persistent interaction data is performed.
"""
import argparse
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import tempfile

ROOT = Path(__file__).resolve().parents[1]
# Exact, case-insensitive category membership, never substring matching.
ATTRACTION_CATEGORIES = {
    'Tourist attraction', 'Attraction', 'Beach', 'Public beach', 'Beach pavillion',
    'Park', 'City park', 'Country park', 'State park', 'National park',
    'Ecological park', 'Memorial park', 'Wildlife park', 'Animal park',
    'Hiking area', 'Trail head', 'Scenic spot', 'Nature preserve', 'Waterfall',
    'Botanical garden', 'Garden', 'Historical landmark', 'Historical place',
    'Landmark', 'Monument', 'Heritage building', 'Museum', 'Art museum',
    "Children's museum", 'Heritage museum', 'Historical place museum',
    'History museum', 'Local history museum', 'Museum of zoology',
    'Natural history museum', 'Science museum', 'War museum', 'Aquarium', 'Zoo',
    'Amusement park', 'Theme park', 'Water park',
}


def normalize(value):
    return ' '.join(value.split()) if isinstance(value, str) else ''


def records(path, errors):
    with gzip.open(path, 'rt', encoding='utf-8') as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                errors['blank_lines'] += 1
                continue
            try:
                record = json.loads(line)
                if not isinstance(record, dict):
                    raise ValueError('Record is not an object')
                yield record
            except ValueError:
                errors['invalid_json_or_nonobject'] += 1


def field_audit(record, counts, present):
    for key, value in record.items():
        present[key] += 1
        if value is None:
            counts[f'{key}:null'] += 1
        elif isinstance(value, str) and not value.strip():
            counts[f'{key}:blank'] += 1


def scalar(db, sql):
    return db.execute(sql).fetchone()[0]


def graph_size(db, table):
    n, users, items = db.execute(f'SELECT COUNT(*),COUNT(DISTINCT u),COUNT(DISTINCT b) FROM {table}').fetchone()
    density = n/(users*items) if users and items else None
    return {'interactions': n, 'users': users, 'attractions': items,
            'density': density, 'sparsity': 1-density if density is not None else None}


def degree_summary(db, table, column):
    hist = Counter(n for (n,) in db.execute(f'SELECT COUNT(*) FROM {table} GROUP BY {column}'))
    entities = sum(hist.values())
    def percentile(fraction):
        accumulated = 0
        for degree, count in sorted(hist.items()):
            accumulated += count
            if accumulated >= math.ceil(entities*fraction):
                return degree
    return {'entities': entities, 'minimum': min(hist, default=0), 'maximum': max(hist, default=0),
            'mean': sum(k*v for k,v in hist.items())/entities if entities else None,
            'median_nearest_rank': percentile(.5), 'p90_nearest_rank': percentile(.9),
            'histogram': dict(sorted(hist.items()))}


def split_audit(db):
    # This is an in-memory/disk audit only: retain latest unique item per user,
    # reserve latest two timestamped items for eligible users, keep others in train.
    db.executescript('''
        DROP TABLE IF EXISTS split;
        CREATE TEMP TABLE split AS SELECT *,CASE
          WHEN t>=0 AND history>=3 AND rn=1 THEN 'test'
          WHEN t>=0 AND history>=3 AND rn=2 THEN 'validation'
          ELSE 'train' END AS part
        FROM (SELECT *,SUM(t>=0) OVER(PARTITION BY u) AS history,
          ROW_NUMBER() OVER(PARTITION BY u ORDER BY t DESC,b) AS rn FROM core);
        CREATE INDEX split_part ON split(part,b);
    ''')
    sizes = {part: scalar(db, f"SELECT COUNT(*) FROM split WHERE part='{part}'")
             for part in ['train', 'validation', 'test']}
    sizes['eligible_users'] = scalar(db, "SELECT COUNT(DISTINCT u) FROM split WHERE part='test'")
    for part in ['validation', 'test']:
        sizes[f'{part}_warm_item_interactions'] = scalar(db, f"SELECT COUNT(*) FROM split s WHERE part='{part}' AND EXISTS(SELECT 1 FROM split t WHERE t.part='train' AND t.b=s.b)")
        sizes[f'{part}_cold_item_interactions'] = sizes[part] - sizes[f'{part}_warm_item_interactions']
    sizes['missing_or_invalid_timestamp_edges'] = scalar(db, 'SELECT COUNT(*) FROM core WHERE t<0')
    sizes['users_with_timestamp_ties'] = scalar(db, 'SELECT COUNT(*) FROM (SELECT u FROM core WHERE t>=0 GROUP BY u HAVING COUNT(*)>COUNT(DISTINCT t))')
    return sizes


def inspect(metadata_path, reviews_path):
    paths = [Path(metadata_path), Path(reviews_path)]
    source_info = {}
    for path in paths:
        with path.open('rb') as stream:
            source_info[path.name] = {'bytes': path.stat().st_size, 'sha256': hashlib.file_digest(stream, 'sha256').hexdigest()}
    category_counts, matched_counts = Counter(), Counter()
    meta_errors, review_errors = Counter(), Counter()
    audits = {name: (Counter(), Counter()) for name in ['metadata', 'reviews']}
    businesses = {}
    missing_meta_id = duplicate_meta_id = conflicting_meta_id = 0
    meta_rows = review_rows = valid_ratings = 0
    selected_categories = {x.casefold() for x in ATTRACTION_CATEGORIES}
    for record in records(paths[0], meta_errors):
        meta_rows += 1
        field_audit(record, *audits['metadata'])
        bid = normalize(record.get('gmap_id'))
        categories = record.get('category') or []
        if not isinstance(categories, list):
            meta_errors['nonlist_category'] += 1
            categories = []
        categories = {normalize(c) for c in categories if normalize(c)}
        category_counts.update(categories)
        matched = sorted(c for c in categories if c.casefold() in selected_categories)
        matched_counts.update(matched)
        if not bid:
            missing_meta_id += 1
            continue
        value = {'name': record.get('name'), 'categories': sorted(categories), 'matched': matched,
                 'address': record.get('address'), 'latitude': record.get('latitude'), 'longitude': record.get('longitude')}
        if bid in businesses:
            duplicate_meta_id += 1
            conflicting_meta_id += businesses[bid] != value
            # Preserve inclusion evidence from any record, while flagging conflicts.
            value['matched'] = sorted(set(value['matched']) | set(businesses[bid]['matched']))
        businesses[bid] = value
    tourist_ids = {bid for bid, value in businesses.items() if value['matched']}
    rating_counts, tourist_rating_counts = Counter(), Counter()
    issues = Counter()
    with tempfile.TemporaryDirectory(prefix='humsafar_hawaii_') as directory, closing(sqlite3.connect(str(Path(directory)/'audit.sqlite'))) as db:
        db.execute('PRAGMA cache_size=-16384')
        db.execute('PRAGMA temp_store=FILE')
        db.executescript('''
            CREATE TABLE all_businesses(b TEXT PRIMARY KEY,has_metadata INTEGER,tourist INTEGER);
            CREATE TABLE ratings(seq INTEGER PRIMARY KEY,u TEXT,b TEXT,r REAL,t INTEGER,fingerprint TEXT);
        ''')
        review_businesses = set()
        for record in records(paths[1], review_errors):
            review_rows += 1
            field_audit(record, *audits['reviews'])
            bid, user = normalize(record.get('gmap_id')), normalize(record.get('user_id'))
            if bid and bid not in review_businesses:
                db.execute('INSERT INTO all_businesses VALUES (?,?,?)', (bid, int(bid in businesses), int(bid in tourist_ids)))
                review_businesses.add(bid)
            value = record.get('rating')
            valid = isinstance(value, (int,float)) and not isinstance(value,bool) and math.isfinite(value) and 1<=value<=5
            rating_counts[str(value)] += 1
            valid_ratings += int(valid)
            if not valid:
                issues['invalid_overall_ratings'] += 1
            if bid not in businesses:
                issues['review_rows_without_matching_metadata'] += 1
            if bid not in tourist_ids:
                continue
            issues['tourist_review_rows'] += 1
            tourist_rating_counts[str(value)] += 1
            if valid:
                issues['valid_tourist_rating_rows_including_missing_users'] += 1
            if not user:
                issues['tourist_reviews_missing_user_id'] += 1
            timestamp = record.get('time')
            valid_time = isinstance(timestamp, (int,float)) and not isinstance(timestamp,bool) and math.isfinite(timestamp) and 0<=timestamp<=253402300799999
            if not valid_time:
                issues['tourist_reviews_missing_or_invalid_time'] += 1
            if valid and user:
                fingerprint = hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()
                db.execute('INSERT INTO ratings(u,b,r,t,fingerprint) VALUES (?,?,?,?,?)',
                           (user,bid,value,int(timestamp) if valid_time else -1,fingerprint))
            if review_rows % 100000 == 0:
                db.commit()
                print(f'Processed {review_rows:,} reviews', flush=True)
        db.commit()
        print(f'Streamed {review_rows:,} reviews; auditing deduplicated tourist graph.', flush=True)
        db.executescript('''
            CREATE INDEX rating_pair ON ratings(u,b);
            CREATE TABLE edges AS SELECT u,b,r,t FROM (
                SELECT *,ROW_NUMBER() OVER(PARTITION BY u,b ORDER BY t DESC,seq DESC) rn FROM ratings) WHERE rn=1;
            CREATE INDEX edge_user ON edges(u);
            CREATE INDEX edge_business ON edges(b);
        ''')
        graph = graph_size(db,'edges')
        duplicates = {
            'repeated_user_attraction_rows_beyond_first': scalar(db, 'SELECT COUNT(*) FROM ratings')-graph['interactions'],
            'pairs_with_multiple_rows': scalar(db, 'SELECT COUNT(*) FROM (SELECT u,b FROM ratings GROUP BY u,b HAVING COUNT(*)>1)'),
            'pairs_with_conflicting_ratings': scalar(db, 'SELECT COUNT(*) FROM (SELECT u,b FROM ratings GROUP BY u,b HAVING MIN(r)!=MAX(r))'),
            'exact_duplicate_review_objects_beyond_first': scalar(db, 'SELECT COUNT(*)-COUNT(DISTINCT fingerprint) FROM ratings'),
        }
        cores = {}
        for k in [2,3,5]:
            db.executescript('DROP TABLE IF EXISTS core; CREATE TABLE core AS SELECT * FROM edges; CREATE INDEX core_u ON core(u); CREATE INDEX core_b ON core(b);')
            rounds = 0
            while True:
                cursor = db.execute('DELETE FROM core WHERE u IN (SELECT u FROM core GROUP BY u HAVING COUNT(*)<?) OR b IN (SELECT b FROM core GROUP BY b HAVING COUNT(*)<?)', (k,k))
                if not cursor.rowcount:
                    break
                rounds += 1
            cores[str(k)] = dict(graph_size(db,'core'), pruning_rounds=rounds,
                user_degrees=degree_summary(db,'core','u'), attraction_degrees=degree_summary(db,'core','b'),
                split_audit=split_audit(db))
            print(f"{k}-core: {cores[str(k)]['interactions']:,} interactions", flush=True)
        timestamps = db.execute('SELECT MIN(t),MAX(t) FROM ratings WHERE t>=0').fetchone()
        result = {
            'sources': source_info, 'parsing_errors': {'metadata': dict(meta_errors), 'reviews': dict(review_errors)},
            'category_filter': {'rule': 'Include gmap_id if ANY metadata category, after whitespace normalization and casefold, exactly equals an allowlist entry. No name, description or MISC Crowd=Tourists matching. Multiple matching categories count a business once. Conflicting duplicate metadata IDs use the union of matching categories.',
                'allowlist': sorted(ATTRACTION_CATEGORIES), 'observed_matching_category_record_counts': dict(matched_counts),
                'excluded_unless_also_allowlisted': ['Restaurants, hotels, stores, tour agencies/operators and rental services', 'Dog/skateboard/athletic/business/technology parks', 'Religious venues without a selected attraction/heritage category', 'Generic recreation centers, geographic features without a selected category'],
                'limitations': ['Categories are proxies for attractions, not verified visitor intent. Residents and tourists are not distinguished.', 'Multi-category commercial listings may enter via Tourist attraction. General parks and gardens may be local recreation.', 'Allowlist is deliberately explicit; other legitimate attractions may be missed. No verified relevance labels are produced.']},
            'counts': {'metadata_rows': meta_rows, 'unique_metadata_businesses': len(businesses),
                'review_rows': review_rows, 'valid_overall_rating_rows': valid_ratings,
                'unique_review_business_ids': len(review_businesses),
                'review_business_ids_without_metadata': scalar(db, 'SELECT COUNT(*) FROM all_businesses WHERE has_metadata=0'),
                'tourist_metadata_businesses': len(tourist_ids),
                'tourist_businesses_with_any_reviews': scalar(db,'SELECT COUNT(*) FROM all_businesses WHERE tourist=1'),
                'valid_identifiable_tourist_rating_rows': scalar(db, 'SELECT COUNT(*) FROM ratings'),
                'deduplicated_tourist_graph': graph},
            'quality': dict(issues, missing_metadata_ids=missing_meta_id, duplicate_metadata_id_rows=duplicate_meta_id,
                            conflicting_metadata_id_rows=conflicting_meta_id, **duplicates),
            'fields': {name: {key: {'absent': (meta_rows if name=='metadata' else review_rows)-n,
                 'null': counts[f'{key}:null'], 'blank_string': counts[f'{key}:blank']}
                 for key,n in sorted(present.items())} for name,(counts,present) in audits.items()},
            'rating_distribution_all_reviews': dict(rating_counts),
            'rating_distribution_tourist_reviews': dict(tourist_rating_counts),
            'attractions_per_user': degree_summary(db,'edges','u'),
            'users_per_attraction': degree_summary(db,'edges','b'),
            'iterative_cores_after_tourist_filter': cores,
            'tourist_review_date_range_utc': [datetime.fromtimestamp(t/1000,timezone.utc).isoformat() if t is not None else None for t in timestamps],
            'sample_selected_businesses': [dict(gmap_id=bid,**businesses[bid]) for bid in sorted(tourist_ids)[:5]],
            'methodology': ['IDs remain strings; join reviews.gmap_id to metadata.gmap_id. Ratings must be numeric, finite and in [1,5]; user IDs must be nonblank.',
                'Degree, density and cores use unique valid user-attraction pairs. Latest timestamp wins repeated pairs; input order resolves tied or missing timestamps. This is inspection, not a saved cleaned training dataset.',
                'All cores are recomputed AFTER the attraction filter, with both user and attraction minimum degree k, iterating to convergence.',
                'Split audit: per eligible user with >=3 timestamped unique attractions, latest one is test and next-latest validation; remaining records train. Ineligible users remain train-only. Attraction IDs break equal-time ties.',
                'Warm-item counts require the held-out attraction to appear in train. Tied timestamps cannot establish strict chronology. Per-user chronological splits are not globally chronological and do not guarantee leakage-free evaluation.',
                'This split is a count/coverage feasibility audit only; no split files or models are saved. Rating prediction feasibility does not guarantee useful top-k relevance labels or enough positive examples.',
                'Original 10-core filename is not taken as a guarantee after filtering or deduplication.',
                'Hawaii users/items cannot be transferred directly to Pakistan destinations. This can support a separate attraction-recommendation experiment, not Pakistan-specific personalization without genuine local interactions.'],
        }
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--metadata', type=Path, default=ROOT/'data/raw/meta-Hawaii.json.gz')
    parser.add_argument('--reviews', type=Path, default=ROOT/'data/raw/review-Hawaii_10.json.gz')
    parser.add_argument('--output', type=Path, default=ROOT/'data/processed/hawaii_inspection.json')
    args = parser.parse_args()
    if args.output.resolve().is_relative_to((ROOT/'data/raw').resolve()) or args.output.resolve() in [args.metadata.resolve(),args.reviews.resolve()]:
        parser.error('Output must not overwrite input data')
    result = inspect(args.metadata,args.reviews)
    result['assessment'] = assess(result)
    result['verification'] = verify(result, [args.metadata, args.reviews])
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps({'counts':result['counts'],'quality':result['quality'],
        'cores':{k:{key:value for key,value in v.items() if key not in ['user_degrees','attraction_degrees']} for k,v in result['iterative_cores_after_tourist_filter'].items()}},indent=2))


def verify(result, paths):
    """Check graph accounting and confirm source bytes have not changed."""
    counts = result['counts']
    graph = counts['deduplicated_tourist_graph']
    if sum(result['rating_distribution_all_reviews'].values()) != counts['review_rows']:
        raise ValueError('Rating count mismatch')
    if counts['valid_identifiable_tourist_rating_rows'] - result['quality']['repeated_user_attraction_rows_beyond_first'] != graph['interactions']:
        raise ValueError('Deduplication count mismatch')
    previous = graph['interactions']
    for k, core in result['iterative_cores_after_tourist_filter'].items():
        if core['interactions'] > previous:
            raise ValueError('Core sizes are inconsistent')
        previous = core['interactions']
        for name in ['user_degrees', 'attraction_degrees']:
            hist = core[name]['histogram']
            if hist and min(map(int, hist)) < int(k):
                raise ValueError('Core minimum degree violated')
            if sum(int(degree)*n for degree,n in hist.items()) != core['interactions']:
                raise ValueError('Core degree totals mismatch')
        split = core['split_audit']
        if sum(split[name] for name in ['train','validation','test']) != core['interactions']:
            raise ValueError('Split partition count mismatch')
    for path in map(Path, paths):
        with path.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != result['sources'][path.name]['sha256']:
                raise ValueError('Source changed during inspection')
    return {'source_checksums_unchanged': True, 'graph_core_degree_and_split_count_consistency': 'passed'}


def assess(result):
    cores = result['iterative_cores_after_tourist_filter']
    eligible = {k: value['split_audit']['eligible_users'] for k,value in cores.items()}
    return {
        'split_feasibility': {k: {
            'users_with_train_validation_test_history': users,
            'has_nonempty_warm_validation_and_test': bool(cores[k]['split_audit']['validation_warm_item_interactions'] and cores[k]['split_audit']['test_warm_item_interactions']),
        } for k,users in eligible.items()},
        'recommended_experiments': [
            'Start with training-only popularity and regularized item-mean baselines, followed by item-item collaborative filtering.',
            'Use a small regularized matrix-factorization model for genuine 1-5 explicit-rating prediction; evaluate MAE/RMSE separately from ranking metrics.',
            'For personalized top-k ranking, consider BPR or WARP only after specifying the observed-rating-to-positive rule, exposure assumptions, and negative sampling. Unobserved items are not verified dislikes.',
            'A hybrid model combining interactions with category/location features is a candidate for sparse histories and cold items; metadata avg_rating/num_of_reviews must not leak held-out outcomes.',
            'Compare core choices for coverage and selection bias. Use warm-item user-aware temporal holdouts, report excluded users/items, and verify chronology and timestamps before freezing splits.',
            'Compute Recall@K/NDCG@K only after defining relevance from genuine held-out feedback. No accuracy or superiority claim follows from graph size alone.',
        ],
        'humsafar_scope': 'Suitable as a candidate Hawaii tourist-attraction research corpus if reported core and holdout sizes support the experiment. It does not provide Pakistan destinations, cross-region user mappings, group fairness labels, budgets, or hotel personalization data for Pakistan.',
        'sources': ['https://surpriselib.com/', 'https://github.com/lyst/lightfm'],
    }


if __name__=='__main__':
    main()
