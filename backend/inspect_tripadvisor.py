"""Stream the Webis archive into a temporary SQLite audit; never extract files.

Run: .venv/Scripts/python.exe backend/inspect_tripadvisor.py
Only the JSON report persists. No training or cleaned interaction data is saved.
"""
import argparse
from collections import Counter
import hashlib
import codecs
from contextlib import ExitStack, closing
import json
import math
from pathlib import Path
import sqlite3
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def array_records(binary):
    """Incrementally decode the users JSON array with a bounded input buffer."""
    stream = codecs.getreader('utf-8')(binary)
    decoder = json.JSONDecoder()
    buffer = ''
    started = False
    eof = False
    while True:
        if not eof:
            chunk = stream.read(65536)
            eof = not chunk
            buffer += chunk
        buffer = buffer.lstrip()
        if not started:
            if not buffer.startswith('['):
                raise ValueError('Expected users JSON array')
            buffer, started = buffer[1:], True
        while True:
            buffer = buffer.lstrip()
            if buffer.startswith(','):
                buffer = buffer[1:].lstrip()
            if buffer.startswith(']'):
                return
            try:
                record, end = decoder.raw_decode(buffer)
            except json.JSONDecodeError:
                if eof:
                    raise ValueError('Incomplete users JSON')
                break
            yield record
            buffer = buffer[end:]


def text(value):
    return ' '.join(value.split()) if isinstance(value, str) else ''


class Fields:
    def __init__(self):
        self.rows = 0
        self.present, self.null, self.blank = Counter(), Counter(), Counter()

    def add(self, record):
        self.rows += 1
        for key, value in record.items():
            self.present[key] += 1
            if value is None:
                self.null[key] += 1
            elif isinstance(value, str) and not value.strip():
                self.blank[key] += 1

    def report(self):
        return {k: {'absent': self.rows - n, 'null': self.null[k], 'blank_string': self.blank[k]}
                for k, n in sorted(self.present.items())}


def scalar(db, sql):
    return db.execute(sql).fetchone()[0]


def degrees(db, sql):
    hist = Counter(row[0] for row in db.execute(sql))
    total = sum(hist.values())
    def quantile(q):
        target = max(1, math.ceil(q * total))
        running = 0
        for degree, count in sorted(hist.items()):
            running += count
            if running >= target:
                return degree
    return {'entities': total, 'min': min(hist, default=0), 'max': max(hist, default=0),
            'mean': sum(k*v for k, v in hist.items()) / total if total else None,
            'median_nearest_rank': quantile(.5), 'p90_nearest_rank': quantile(.9),
            'histogram': dict(sorted(hist.items()))}


def size(db, table):
    return dict(zip(['interactions', 'users', 'hotels'], db.execute(
        f'SELECT COUNT(*),COUNT(DISTINCT u),COUNT(DISTINCT h) FROM {table}').fetchone()))


def inspect(archive_path):
    archive_path = Path(archive_path)
    with archive_path.open('rb') as archive_file:
        source_hash = hashlib.file_digest(archive_file, 'sha256').hexdigest()
    schemas = {k: Fields() for k in ['users', 'hotels', 'reviews', 'hotel_location', 'review_detail_rating']}
    members, errors, examples = [], [], {}
    invalid = Counter()
    rating_values = Counter()
    with tempfile.TemporaryDirectory(prefix='humsafar_tripadvisor_') as directory, ExitStack() as stack:
        db = stack.enter_context(closing(sqlite3.connect(str(Path(directory) / 'audit.sqlite'))))
        db.execute('PRAGMA cache_size=-16384')
        db.execute('PRAGMA temp_store=FILE')
        db.executescript('''
            CREATE TABLE profiles(u TEXT);
            CREATE TABLE hotels(h TEXT, name TEXT, country TEXT, city TEXT, location TEXT);
            CREATE TABLE reviews(u TEXT,h TEXT,r REAL,rid TEXT,day TEXT,fingerprint TEXT,valid INTEGER,identifiable INTEGER);
        ''')
        with tarfile.open(archive_path, 'r|gz') as archive:
            for member in archive:
                members.append({'path': member.name, 'bytes': member.size, 'is_file': member.isfile()})
                if not member.isfile():
                    continue
                if member.name == 'users.json':
                    for user in array_records(archive.extractfile(member)):
                        schemas['users'].add(user)
                        db.execute('INSERT INTO profiles VALUES (?)', (text(user.get('username')),))
                    db.commit()
                elif member.name.startswith('reviews/') and member.name.endswith('.json'):
                    try:
                        hotel = json.load(archive.extractfile(member))
                    except (ValueError, UnicodeError) as exc:
                        errors.append({'member': member.name, 'error': str(exc)})
                        continue
                    schemas['hotels'].add(hotel)
                    location = hotel.get('location') or {}
                    schemas['hotel_location'].add(location)
                    country, city = text(location.get('country')), text(location.get('city'))
                    db.execute('INSERT INTO hotels VALUES (?,?,?,?,?)',
                               (member.name, text(hotel.get('name')), country, city, json.dumps(location, sort_keys=True)))
                    if 'hotel' not in examples:
                        examples['hotel'] = {'archive_path_identifier': member.name,
                            'name': hotel.get('name'), 'location': location,
                            'review_keys': sorted(hotel.get('reviews', [{}])[0])}
                    for review in hotel.get('reviews', []):
                        schemas['reviews'].add(review)
                        if isinstance(review.get('detail_rating'), dict):
                            schemas['review_detail_rating'].add(review['detail_rating'])
                        value = review.get('rating')
                        rating_values[str(value)] += 1
                        valid = (isinstance(value, (int, float)) and not isinstance(value, bool)
                                 and math.isfinite(value) and 1 <= value <= 5)
                        if not valid:
                            invalid['outside_1_to_5_or_missing_or_nonnumeric'] += 1
                        elif value != int(value):
                            invalid['fractional_within_range'] += 1
                        user = text(review.get('user'))
                        # This shared anonymous identity is explicitly present in the archive.
                        identifiable = bool(user) and user.casefold() != 'a tripadvisor user'
                        if not user:
                            invalid['missing_or_blank_user'] += 1
                        elif not identifiable:
                            invalid['anonymous_shared_user'] += 1
                        fingerprint = hashlib.sha256(json.dumps(review, sort_keys=True, ensure_ascii=True).encode()).hexdigest()
                        db.execute('INSERT INTO reviews VALUES (?,?,?,?,?,?,?,?)',
                            (user, member.name, value if valid else None,
                             str(review['id']) if review.get('id') is not None else None,
                             text(review.get('date')), fingerprint, int(valid), int(identifiable)))
                    if schemas['hotels'].rows % 500 == 0:
                        db.commit()
                        print(f"Inspected {schemas['hotels'].rows} hotels / {schemas['reviews'].rows} reviews", flush=True)
        db.commit()
        print('Archive streamed; aggregating interactions and filtering scenarios.', flush=True)
        db.executescript('''
            CREATE INDEX review_pair ON reviews(u,h);
            CREATE INDEX profile_name ON profiles(u);
            CREATE TABLE edges AS SELECT u,h,AVG(r) AS r FROM reviews
              WHERE valid=1 AND identifiable=1 GROUP BY u,h;
            CREATE INDEX edge_user ON edges(u);
            CREATE INDEX edge_hotel ON edges(h);
        ''')
        # No interaction records are changed or persisted: this is an audit scenario.
        filtering = {}
        for minimum_user, minimum_hotel in [(2, 5), (5, 5)]:
            db.executescript('DROP TABLE IF EXISTS core; CREATE TABLE core AS SELECT * FROM edges; CREATE INDEX core_u ON core(u); CREATE INDEX core_h ON core(h);')
            rounds = 0
            while True:
                cursor = db.execute('''DELETE FROM core WHERE u IN
                    (SELECT u FROM core GROUP BY u HAVING COUNT(*) < ?) OR h IN
                    (SELECT h FROM core GROUP BY h HAVING COUNT(*) < ?)''', (minimum_user, minimum_hotel))
                if not cursor.rowcount:
                    break
                rounds += 1
            filtering[f'user_at_least_{minimum_user}_hotel_at_least_{minimum_hotel}_iterative_core'] = dict(size(db, 'core'), pruning_rounds=rounds)
        profile_count = scalar(db, 'SELECT COUNT(DISTINCT u) FROM profiles WHERE u != ""')
        quality = {
            'invalid_rating_and_identity_counts': dict(invalid),
            'duplicate_profile_rows_beyond_first': scalar(db, 'SELECT COUNT(*)-COUNT(DISTINCT u) FROM profiles'),
            'duplicate_hotel_member_paths_beyond_first': scalar(db, 'SELECT COUNT(*)-COUNT(DISTINCT h) FROM hotels'),
            'repeated_review_ids_beyond_first': scalar(db, 'SELECT COUNT(rid)-COUNT(DISTINCT rid) FROM reviews'),
            'review_ids_associated_with_multiple_hotels': scalar(db, 'SELECT COUNT(*) FROM (SELECT rid FROM reviews WHERE rid IS NOT NULL GROUP BY rid HAVING COUNT(DISTINCT h)>1)'),
            'exact_review_duplicates_within_hotel_beyond_first': scalar(db, 'SELECT COALESCE(SUM(n-1),0) FROM (SELECT COUNT(*) n FROM reviews GROUP BY h,fingerprint HAVING COUNT(*)>1)'),
            'repeated_identifiable_valid_pairs_beyond_first': scalar(db, 'SELECT COUNT(*) FROM reviews WHERE valid=1 AND identifiable=1') - scalar(db, 'SELECT COUNT(*) FROM edges'),
            'pairs_with_conflicting_valid_ratings': scalar(db, 'SELECT COUNT(*) FROM (SELECT u,h FROM reviews WHERE valid=1 AND identifiable=1 GROUP BY u,h HAVING MIN(r)!=MAX(r))'),
            'identifiable_rating_users_without_profile': scalar(db, 'SELECT COUNT(DISTINCT r.u) FROM reviews r WHERE valid=1 AND identifiable=1 AND NOT EXISTS (SELECT 1 FROM profiles p WHERE p.u=r.u)'),
        }
        countries = [dict(zip(['country', 'hotels'], row)) for row in db.execute('SELECT country,COUNT(*) FROM hotels GROUP BY country ORDER BY COUNT(*) DESC')]
        location_checks = {
            'hotels_missing_country': scalar(db, "SELECT COUNT(*) FROM hotels WHERE country=''"),
            'hotels_missing_city': scalar(db, "SELECT COUNT(*) FROM hotels WHERE city=''"),
            'distinct_nonblank_country_labels': scalar(db, "SELECT COUNT(DISTINCT country) FROM hotels WHERE country!=''"),
            'distinct_nonblank_city_country_pairs': scalar(db, "SELECT COUNT(*) FROM (SELECT DISTINCT city,country FROM hotels WHERE city!='' AND country!='')"),
            'country_case_or_whitespace_variants': [list(row) for row in db.execute('SELECT LOWER(TRIM(country)),GROUP_CONCAT(DISTINCT country) FROM hotels GROUP BY LOWER(TRIM(country)) HAVING COUNT(DISTINCT country)>1')],
            'same_hotel_name_multiple_locations_examples': [list(row) for row in db.execute("SELECT name,COUNT(DISTINCT location) FROM hotels WHERE name!='' GROUP BY name HAVING COUNT(DISTINCT location)>1 LIMIT 10")],
            'same_city_label_in_multiple_countries_examples': [list(row) for row in db.execute("SELECT city,GROUP_CONCAT(DISTINCT country) FROM hotels WHERE city!='' AND country!='' GROUP BY city HAVING COUNT(DISTINCT country)>1 LIMIT 10")],
            'pakistan_hotels': scalar(db, "SELECT COUNT(*) FROM hotels WHERE LOWER(TRIM(country))='pakistan'"),
            'pakistan_identifiable_unique_pairs': scalar(db, "SELECT COUNT(*) FROM edges WHERE h IN (SELECT h FROM hotels WHERE LOWER(TRIM(country))='pakistan')"),
            'pakistan_hotel_details': [dict(zip(['archive_path_identifier', 'name', 'city', 'country', 'identifiable_interactions'], row))
                for row in db.execute("SELECT h.h,h.name,h.city,h.country,COUNT(e.u) FROM hotels h LEFT JOIN edges e ON h.h=e.h WHERE LOWER(TRIM(h.country))='pakistan' GROUP BY h.h,h.name,h.city,h.country")],
            'unique_interactions_with_both_city_and_country': scalar(db, "SELECT COUNT(*) FROM edges WHERE h IN (SELECT h FROM hotels WHERE city!='' AND country!='')"),
            'geographic_granularity_flags': [dict(zip(['country_label', 'hotels'], row)) for row in db.execute("SELECT country,COUNT(*) FROM hotels WHERE country='Caribbean' GROUP BY country")],
            'country_counts': countries,
        }
        result = {
            'archive': {'file': archive_path.name, 'compressed_bytes': archive_path.stat().st_size,
                        'sha256': source_hash,
                        'member_count': len(members), 'uncompressed_bytes': sum(m['bytes'] for m in members),
                        'first_members': members[:12], 'largest_member_bytes': max(m['bytes'] for m in members)},
            'identifiers': {'user': 'reviews[].user joined to users.json username; usernames are not verified stable numeric IDs',
                            'hotel': 'archive reviews/<filename>.json path; no numeric hotel ID assumed',
                            'review': 'reviews[].id', 'rating': 'reviews[].rating, numeric 1 through 5 inclusive',
                            'hotel_location': 'location.country and location.city, when present; user.location is not hotel location'},
            'counts': {'profile_rows': schemas['users'].rows, 'unique_profile_usernames': profile_count,
                'hotel_records': schemas['hotels'].rows, 'unique_hotel_paths': scalar(db, 'SELECT COUNT(DISTINCT h) FROM hotels'),
                'total_review_rows': schemas['reviews'].rows,
                'valid_rating_rows_including_anonymous': scalar(db, 'SELECT COUNT(*) FROM reviews WHERE valid=1'),
                'unique_review_user_labels_including_anonymous': scalar(db, "SELECT COUNT(DISTINCT u) FROM reviews WHERE u!=''"),
                'identifiable_valid_rating_rows': scalar(db, 'SELECT COUNT(*) FROM reviews WHERE valid=1 AND identifiable=1'),
                'deduplicated_identifiable_valid_interactions': size(db, 'edges')},
            'schemas_missing_values': {k: {'record_count': v.rows, 'fields': v.report()} for k, v in schemas.items()},
            'rating_distribution_all_reviews': dict(rating_values), 'quality': quality,
            'distinct_hotels_per_identifiable_user': degrees(db, 'SELECT COUNT(*) FROM edges GROUP BY u'),
            'distinct_identifiable_users_per_hotel': degrees(db, 'SELECT COUNT(*) FROM edges GROUP BY h'),
            'valid_rating_rows_per_hotel_including_anonymous': degrees(db, 'SELECT COUNT(*) FROM reviews WHERE valid=1 GROUP BY h'),
            'top_user_labels_by_review_count': [list(row) for row in db.execute('SELECT u,COUNT(*) FROM reviews GROUP BY u ORDER BY COUNT(*) DESC LIMIT 15')],
            'filtering_scenarios': filtering, 'locations': location_checks, 'sample_schema': examples,
            'parse_errors': errors,
            'interpretation': [
                'Filtering excludes blank users and the observed shared label A TripAdvisor user, invalid ratings, and collapses repeated user-hotel pairs. AVG is only a temporary audit representation; no training data is saved.',
                'Repeated review IDs, including those spanning hotels, remain unresolved in audit estimates; they require review before splitting or training.',
                'Iterative degree thresholds are audit scenarios, not finalized eligibility or train/test splits. Counts precede holdouts.',
                'Named-user overlap supports collaborative filtering and explicit-rating supervised objectives, subject to coverage and leakage-safe evaluation. Unobserved hotels are not labeled dislikes.',
                'Personalized ranking relevance thresholds, negatives and chronological user-aware splits still require design; no accuracy is estimated.',
                'Hotel aggregate user_rating and review_count are not individual rating labels and can leak future information.',
                'Same names/cities in different locations are review flags, not proven errors. Locations are not geocoded or corrected; geographic aliases are not inferred.',
                'Country labels have mixed granularity: Caribbean is a region, not a country. Country/city grouping trims whitespace without inferring missing locations.',
                'Corpus is historical. Pakistan country coverage must be checked before using it for Pakistan-specific hotel recommendations; existing destination names have not been joined.',
                'Hotel degree histogram excludes hotels with zero identifiable valid interactions; all catalog counts are separately reported.',
            ],
        }
        result['quality']['hotels_without_identifiable_valid_interactions'] = scalar(db, 'SELECT COUNT(*) FROM hotels WHERE h NOT IN (SELECT h FROM edges)')
        result['counts']['interaction_density'] = (size(db, 'edges')['interactions'] / (size(db, 'edges')['users'] * size(db, 'edges')['hotels'])) if size(db, 'edges')['users'] and size(db, 'edges')['hotels'] else 0
        result['suitability'] = {
            'global_research': 'Real user-hotel ratings support collaborative filtering and explicit-rating objectives in principle. Assess sparse-user degree distributions and surviving cores before selecting ranking evaluation splits.',
            'pakistan_destination_conditioned_hotels': f"Explicitly Pakistan-labelled coverage: {location_checks['pakistan_hotels']} hotels and {location_checks['pakistan_identifiable_unique_pairs']} unique identifiable interactions. Missing-country hotels are not assumed to be Pakistani; no destination mapping has been inferred.",
            'usable_data_estimates': f"{size(db, 'edges')['interactions']} unique identifiable pairs before degree filtering; {filtering['user_at_least_2_hotel_at_least_5_iterative_core']['interactions']} in the iterative user>=2, hotel>=5 core. Audit counts precede unresolved review-ID deduplication, location requirements and evaluation holdouts.",
        }
        db.close()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, default=ROOT / 'data/raw/corpus-webis-tripad-14.tar.gz')
    parser.add_argument('--output', type=Path, default=ROOT / 'data/processed/tripadvisor_inspection.json')
    args = parser.parse_args()
    if args.output.resolve().is_relative_to((ROOT / 'data/raw').resolve()) or args.output.resolve() == args.archive.resolve():
        parser.error('Report must not overwrite raw data')
    result = inspect(args.archive)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(json.dumps({'counts': result['counts'], 'quality': result['quality'],
                      'filtering_scenarios': result['filtering_scenarios'],
                      'pakistan_hotels': result['locations']['pakistan_hotels']}, indent=2))


if __name__ == '__main__':
    main()
