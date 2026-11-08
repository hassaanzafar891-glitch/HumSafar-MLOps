"""Reproducible Hawaii attraction preparation, without fitting a model.

Run from project root: .venv/Scripts/python.exe -m backend.prepare_hawaii
"""
import argparse
from collections import Counter
from contextlib import closing
import csv
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import tempfile

from backend.inspect_hawaii import ATTRACTION_CATEGORIES, normalize, records, scalar, graph_size

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'data/processed/hawaii'


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def select_metadata(path):
    """Apply exactly the inspection allowlist, ANY-category rule and ID union."""
    selected, seen, matched_by_id = {}, set(), {}
    errors, counts = Counter(), Counter()
    allowlist = {c.casefold() for c in ATTRACTION_CATEGORIES}
    for record in records(path, errors):
        counts['metadata_rows'] += 1
        bid = normalize(record.get('gmap_id'))
        categories = record.get('category') or []
        if not isinstance(categories, list):
            errors['nonlist_category'] += 1
            categories = []
        matched = {normalize(c) for c in categories if normalize(c).casefold() in allowlist}
        if not bid:
            counts['missing_metadata_id_rows'] += 1
            continue
        counts['duplicate_metadata_id_rows'] += bid in seen
        seen.add(bid)
        matched_by_id.setdefault(bid, set()).update(matched)
        if matched_by_id[bid]:
            selected[bid] = {'source_metadata': record,
                             'matched_attraction_categories': sorted(matched_by_id[bid])}
    if errors:
        raise ValueError(f'Metadata parsing/schema issues require review: {dict(errors)}')
    counts['unique_metadata_businesses'] = len(seen)
    counts['selected_metadata_businesses'] = len(selected)
    return selected, dict(counts)


def deduplicate_and_core(db, minimum=5):
    db.executescript('''
        CREATE INDEX review_pair ON reviews(u,b);
        CREATE TABLE edges AS SELECT u,b,r,t,seq FROM (
          SELECT *,ROW_NUMBER() OVER(PARTITION BY u,b ORDER BY t DESC,seq DESC) AS rn
          FROM reviews) WHERE rn=1;
        CREATE INDEX edges_u ON edges(u);
        CREATE INDEX edges_b ON edges(b);
        CREATE TABLE core AS SELECT * FROM edges;
        CREATE INDEX core_u ON core(u);
        CREATE INDEX core_b ON core(b);
    ''')
    rounds = 0
    while True:
        deleted = db.execute('''DELETE FROM core WHERE u IN
          (SELECT u FROM core GROUP BY u HAVING COUNT(*)<?) OR b IN
          (SELECT b FROM core GROUP BY b HAVING COUNT(*)<?)''', (minimum, minimum)).rowcount
        if not deleted:
            return rounds
        rounds += 1


def split_core(db):
    # Match inspection: timestamp descending, then original attraction ID ASC.
    db.executescript('''
        CREATE TABLE split AS SELECT u,b,r,t,seq,
          CASE WHEN rn=1 THEN 'test' WHEN rn=2 THEN 'validation' ELSE 'train' END AS part
        FROM (SELECT *,ROW_NUMBER() OVER(PARTITION BY u ORDER BY t DESC,b ASC) rn FROM core);
        CREATE INDEX split_user ON split(u,part);
        CREATE INDEX split_item ON split(b,part);
    ''')


def audit_split(db):
    checks = {
        'duplicate_pairs': scalar(db, 'SELECT COUNT(*) FROM split') - scalar(db,'SELECT COUNT(*) FROM (SELECT u,b FROM split GROUP BY u,b)'),
        'cross_split_pair_overlaps': scalar(db,'SELECT COUNT(*) FROM (SELECT u,b FROM split GROUP BY u,b HAVING COUNT(DISTINCT part)>1)'),
        'heldout_users_absent_from_train': scalar(db,"SELECT COUNT(DISTINCT u) FROM split s WHERE part!='train' AND NOT EXISTS(SELECT 1 FROM split t WHERE t.u=s.u AND t.part='train')"),
        'heldout_attractions_absent_from_train': scalar(db,"SELECT COUNT(DISTINCT b) FROM split s WHERE part!='train' AND NOT EXISTS(SELECT 1 FROM split t WHERE t.b=s.b AND t.part='train')"),
        'invalid_ratings': scalar(db,'SELECT COUNT(*) FROM split WHERE r IS NULL OR r<1 OR r>5'),
        'invalid_timestamps': scalar(db,'SELECT COUNT(*) FROM split WHERE t IS NULL OR t<0'),
        'users_without_training_history': scalar(db,"SELECT COUNT(*) FROM (SELECT u FROM split GROUP BY u HAVING SUM(part='train')=0)"),
        'users_with_wrong_holdout_counts': scalar(db,"SELECT COUNT(*) FROM (SELECT u FROM split GROUP BY u HAVING SUM(part='test')!=1 OR SUM(part='validation')!=1)"),
        'users_with_timestamp_order_violations': scalar(db,"""SELECT COUNT(*) FROM (
          SELECT u FROM split GROUP BY u HAVING
          MAX(CASE WHEN part='train' THEN t END)>MAX(CASE WHEN part='validation' THEN t END)
          OR MAX(CASE WHEN part='validation' THEN t END)>MAX(CASE WHEN part='test' THEN t END))"""),
    }
    diagnostics = {
        'users_with_any_timestamp_ties': scalar(db,'SELECT COUNT(*) FROM (SELECT u FROM core GROUP BY u HAVING COUNT(*)>COUNT(DISTINCT t))'),
        'users_with_equal_train_validation_boundary': scalar(db,"SELECT COUNT(*) FROM (SELECT u FROM split GROUP BY u HAVING MAX(CASE WHEN part='train' THEN t END)=MAX(CASE WHEN part='validation' THEN t END))"),
        'users_with_equal_validation_test_boundary': scalar(db,"SELECT COUNT(*) FROM (SELECT u FROM split GROUP BY u HAVING MAX(CASE WHEN part='validation' THEN t END)=MAX(CASE WHEN part='test' THEN t END))"),
        'training_rows_later_than_earliest_test_globally': scalar(db,"SELECT COUNT(*) FROM split WHERE part='train' AND t>(SELECT MIN(t) FROM split WHERE part='test')"),
        'minimum_train_interactions_per_user': scalar(db,"SELECT MIN(n) FROM (SELECT COUNT(*) n FROM split WHERE part='train' GROUP BY u)"),
    }
    return {'checks': checks, 'diagnostics': diagnostics,
            'structural_checks_passed': not any(checks.values())}


def export_rows(db, path, sql, header):
    with Path(path).open('w', encoding='utf-8', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(header)
        writer.writerows(db.execute(sql))


def prepare(metadata_path=ROOT/'data/raw/meta-Hawaii.json.gz', reviews_path=ROOT/'data/raw/review-Hawaii_10.json.gz', output=OUTPUT):
    metadata_path, reviews_path, output = map(Path, [metadata_path,reviews_path,output])
    if output.resolve().is_relative_to((ROOT/'data/raw').resolve()):
        raise ValueError('Output must be outside data/raw')
    inputs = {p.name: {'sha256': sha256(p), 'bytes': p.stat().st_size} for p in [metadata_path,reviews_path]}
    inspection = json.loads((ROOT/'data/processed/hawaii_inspection.json').read_text(encoding='utf-8'))
    if sorted(ATTRACTION_CATEGORIES) != inspection['category_filter']['allowlist']:
        raise ValueError('Category allowlist differs from existing inspection; resolve before preparation')
    metadata, metadata_counts = select_metadata(metadata_path)
    counts, errors = Counter(), Counter()
    print(f'Selected {len(metadata):,} attraction metadata IDs using the existing allowlist.', flush=True)
    with tempfile.TemporaryDirectory(prefix='humsafar_prepare_') as temp, closing(sqlite3.connect(str(Path(temp)/'prepare.sqlite'))) as db:
        db.execute('PRAGMA cache_size=-16384')
        db.execute('PRAGMA temp_store=FILE')
        db.execute('CREATE TABLE reviews(seq INTEGER PRIMARY KEY,u TEXT,b TEXT,r REAL,t INTEGER,fingerprint TEXT)')
        for seq, record in enumerate(records(reviews_path,errors), 1):
            counts['all_review_rows'] += 1
            bid = normalize(record.get('gmap_id'))
            if bid not in metadata:
                continue
            counts['tourist_review_rows'] += 1
            user, rating, timestamp = normalize(record.get('user_id')), record.get('rating'), record.get('time')
            if not user:
                counts['excluded_missing_user'] += 1
                continue
            if not isinstance(rating,(int,float)) or isinstance(rating,bool) or not math.isfinite(rating) or not 1<=rating<=5:
                counts['excluded_invalid_rating'] += 1
                continue
            if not isinstance(timestamp,(int,float)) or isinstance(timestamp,bool) or not math.isfinite(timestamp) or not 0<=timestamp<=253402300799999 or timestamp!=int(timestamp):
                counts['excluded_invalid_or_fractional_timestamp_ms'] += 1
                continue
            db.execute('INSERT INTO reviews VALUES (?,?,?,?,?,?)',
                (seq,user,bid,rating,int(timestamp),hashlib.sha256(json.dumps(record,sort_keys=True).encode()).hexdigest()))
            counts['valid_tourist_review_rows'] += 1
            if seq % 100000==0:
                db.commit()
                print(f'Scanned {seq:,} reviews',flush=True)
        db.commit()
        if errors:
            raise ValueError(f'Review parsing errors require review: {dict(errors)}')
        print('Deduplicating, computing iterative 5-core and auditing splits.',flush=True)
        rounds = deduplicate_and_core(db)
        before_core, core = graph_size(db,'edges'), graph_size(db,'core')
        if not core['interactions']:
            raise ValueError('No 5-core remains; no splits written')
        split_core(db)
        audit = audit_split(db)
        quality = {
            'duplicate_pair_rows_removed': counts['valid_tourist_review_rows']-before_core['interactions'],
            'exact_duplicate_review_rows_beyond_first': scalar(db,'SELECT COUNT(*)-COUNT(DISTINCT fingerprint) FROM reviews'),
            'pairs_with_conflicting_ratings': scalar(db,'SELECT COUNT(*) FROM (SELECT u,b FROM reviews GROUP BY u,b HAVING MIN(r)!=MAX(r))'),
            'duplicate_pairs_with_equal_timestamps': scalar(db,'SELECT COUNT(*) FROM (SELECT u,b FROM reviews GROUP BY u,b HAVING COUNT(*)>COUNT(DISTINCT t))'),
            'rows_removed_by_5core': before_core['interactions']-core['interactions'],
        }
        db.executescript('''
            CREATE TABLE users AS SELECT u,ROW_NUMBER() OVER(ORDER BY u COLLATE BINARY)-1 AS user_index FROM (SELECT DISTINCT u FROM core);
            CREATE UNIQUE INDEX users_u ON users(u);
            CREATE TABLE attractions AS SELECT b,ROW_NUMBER() OVER(ORDER BY b COLLATE BINARY)-1 AS attraction_index FROM (SELECT DISTINCT b FROM core);
            CREATE UNIQUE INDEX attractions_b ON attractions(b);
        ''')
        output.mkdir(parents=True,exist_ok=True)
        header = ['user_id','gmap_id','user_index','attraction_index','rating','timestamp_ms','source_review_record']
        query = 'SELECT s.u,s.b,u.user_index,a.attraction_index,s.r,s.t,s.seq FROM split s JOIN users u ON s.u=u.u JOIN attractions a ON s.b=a.b'
        export_rows(db,output/'interactions.csv',query+' ORDER BY u.user_index,s.t,s.b',header)
        for part in ['train','validation','test']:
            export_rows(db,output/f'{part}.csv',query+f" WHERE s.part='{part}' ORDER BY u.user_index,s.t,s.b",header)
        export_rows(db,output/'user_mapping.csv','SELECT u,user_index FROM users ORDER BY user_index',['user_id','user_index'])
        export_rows(db,output/'attraction_mapping.csv','SELECT b,attraction_index FROM attractions ORDER BY attraction_index',['gmap_id','attraction_index'])
        metadata_quality = Counter()
        with (output/'attractions.jsonl').open('w',encoding='utf-8') as stream:
            for bid,index in db.execute('SELECT b,attraction_index FROM attractions ORDER BY attraction_index'):
                value = metadata[bid]
                source = value['source_metadata']
                for name in ['name','address','latitude','longitude','category','description']:
                    if source.get(name) is None or source.get(name)=='':
                        metadata_quality[f'missing_{name}'] += 1
                for name,limit in [('latitude',90),('longitude',180)]:
                    v=source.get(name)
                    if v is not None and (not isinstance(v,(int,float)) or isinstance(v,bool) or not math.isfinite(v) or not -limit<=v<=limit):
                        metadata_quality[f'invalid_{name}'] += 1
                stream.write(json.dumps(dict(attraction_index=index,**value),ensure_ascii=False)+'\n')
        split_counts = {part: scalar(db,f"SELECT COUNT(*) FROM split WHERE part='{part}'") for part in ['train','validation','test']}
        checksums_unchanged = all(sha256(p)==inputs[p.name]['sha256'] for p in [metadata_path,reviews_path])
        if not checksums_unchanged:
            raise RuntimeError('Source bytes changed during preparation')
        report = {
            'sources':inputs,'category_filter':inspection['category_filter'],
            'counts':dict(counts,**metadata_counts),'quality':quality,'metadata_quality':dict(metadata_quality),
            'deduplicated_before_core':before_core,'five_core':dict(core,pruning_rounds=rounds),
            'split_counts':split_counts,'audit':audit,'source_checksums_unchanged':checksums_unchanged,
            'matches_prior_inspection_5core': all(core[k]==inspection['iterative_cores_after_tourist_filter']['5'][k] for k in ['interactions','users','attractions']),
            'rules': {
                'duplicate_pairs':'Latest valid timestamp wins; ties retain the later record in the original review stream, matching inspection. The retained rating is genuine; ratings are not averaged.',
                'split':'Per user, order timestamp_ms DESC then original gmap_id ASC (binary lexicographic). First=test, second=validation, remaining=train. Equal timestamps have deterministic ordering, not proven real-world chronology.',
                'mapping':'Zero-based indexes of distinct 5-core original IDs sorted with binary lexicographic string ordering. Stable for identical input/core; rebuilding after catalog changes may shift indexes.',
                'metadata':'Last source metadata record per ID; inclusion categories unioned across records exactly as inspection. Original record preserved under source_metadata, including name/category/coordinates/address and all other available fields. No location inferred.',
                'validation':'Malformed JSON fails preparation; blank/invalid identity/rating/timestamp rows are excluded and counted. Timestamps are integer epoch milliseconds. Cold-start or structural failures are reported without moving rows between splits.',
            },
            'limitations': [
                '5-core selection uses the entire interaction graph including eventual holdouts, favoring active users/popular attractions and exposing future graph membership. This is a retrospective warm-start benchmark, not a prospective unbiased test.',
                'User-wise chronology is not a single global time cutoff; other users training records can postdate held-out events. Equal timestamp boundaries do not establish strict chronology.',
                'Latest-review deduplication uses complete history, including future updates; earlier ratings for a pair are discarded.',
                'Attraction metadata is a snapshot with no as-of-event history. avg_rating, num_of_reviews, relative_results, and review-derived fields must not enter evaluation features without leakage analysis. They are preserved for provenance, not declared safe features.',
                'Ratings do not verify visitor identity or tourist intent; category filtering has false positives/negatives. Explicit rating imbalance and exposure bias remain; unobserved items are not verified dislikes.',
                'Hawaii is the first real-world international HumSafar benchmark. Expansion requires genuine catalog/interaction data; learned IDs alone cannot generalize to unseen international attractions or users.',
                'No supervised relevance threshold, negative sampling, trained model, group fairness labels, or group consensus outcomes are created here.',
            ],
        }
        generated = ['interactions.csv','train.csv','validation.csv','test.csv','user_mapping.csv','attraction_mapping.csv','attractions.jsonl']
        report['generated_files']={name:{'bytes':(output/name).stat().st_size,'sha256':sha256(output/name)} for name in generated}
        (output/'audit.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
        if not audit['structural_checks_passed']:
            raise ValueError('Prepared split has audit failures; protocol was not changed. Review audit.json before use.')
        return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=OUTPUT)
    args=parser.parse_args()
    report=prepare(output=args.output)
    print(json.dumps({k:report[k] for k in ['five_core','split_counts','quality','metadata_quality','audit','matches_prior_inspection_5core']},indent=2))


if __name__=='__main__':
    main()
