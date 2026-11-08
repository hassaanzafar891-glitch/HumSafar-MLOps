"""Adapt only actual local datasets into the unified catalog; no downloads."""
import argparse
import csv
import json
import tarfile

from backend.catalog import Destination, ROOT, stable_id, country_mapping, NON_COUNTRY_LABELS, ingest, CATALOG_DIR
from backend.train_baselines import checksum


def optional(value):
    return value if isinstance(value,str) and value.strip() else None


def record(source,source_id,name,kind,country,region,lat,lon,categories,description,address,scope,modes,provenance):
    return Destination(1,stable_id(source,source_id),name,kind,country,region,lat,lon,categories,
                       description,address,source,source_id,scope,modes,provenance).validate()


def pakistan_records():
    with (ROOT/'data/processed/destinations_cleaned.csv').open(encoding='utf-8',newline='') as stream:
        for row in csv.DictReader(stream):
            yield record('pakistan_tourism',row['_key'],row['_key'],'attraction','Pakistan',row['district'],
                float(row['latitude']),float(row['longitude']),[row['category']],optional(row['Desc']),None,
                'Pakistan source destination catalog',['pakistan_tfidf','metadata_preference'],
                {'country_basis':'explicit Pakistan dataset context, not geocoding','source_file':'data/processed/destinations_cleaned.csv',
                 'region_basis':'source district field contains province/territory-level labels','recommendation_text':row['recommendation_text']})


def hawaii_records():
    model_meta=json.loads((ROOT/'models/hawaii_bpr/metadata.json').read_text(encoding='utf-8'))
    compatible=set(model_meta['items'])
    with (ROOT/'data/processed/hawaii/attractions.jsonl').open(encoding='utf-8') as stream:
        for line in stream:
            row=json.loads(line)['source_metadata']
            lat,lon=row.get('latitude'),row.get('longitude')
            if lat is None or lon is None or not (18<=lat<=23 and -161<=lon<=-154):
                raise ValueError('Hawaii country-context adapter requires location review outside the checked regional bounds')
            modes=['metadata_preference']+(['hawaii_bpr'] if row['gmap_id'] in compatible else [])
            yield record('google_local_hawaii',row['gmap_id'],row['name'],'attraction','United States','Hawaii',
                lat,lon,sorted(set(row.get('category') or [])),optional(row.get('description')),optional(row.get('address')),
                'Hawaii, United States: prepared attraction subset',modes,
                {'country_basis':'explicit Hawaii dataset context; coordinates checked against conservative Hawaii regional bounds',
                 'region_basis':'source collection; city not inferred from address',
                 'source_file':'data/processed/hawaii/attractions.jsonl','source_url':row.get('url')})


def tripadvisor_records():
    # Ignore users.json and every interaction field; parse one hotel file at a
    # time from the archive without extracting it or persisting its review data.
    with tarfile.open(ROOT/'data/raw/corpus-webis-tripad-14.tar.gz','r|gz') as archive:
        for member in archive:
            if not member.isfile() or not member.name.startswith('reviews/') or not member.name.endswith('.json'):
                continue
            row=json.load(archive.extractfile(member))
            location=row.get('location') or {}
            label=optional(location.get('country'))
            country=country_mapping(label)
            region=optional(location.get('city')) or optional(location.get('region')) or (label if label in NON_COUNTRY_LABELS else None)
            yield record('webis_tripadvisor_2014',member.name,row['name'],'hotel',country,region,None,None,[],
                optional(row.get('description')),None,'International historical hotel metadata; source country/territory labels',
                ['metadata_preference'],{'country_basis':'source location.country with explicit aliases; missing/non-country labels remain null',
                 'source_file':'data/raw/corpus-webis-tripad-14.tar.gz','archive_member':member.name,
                 'source_location':location,'original_country_label':label})


def build():
    sources=[ROOT/'data/processed/destinations_cleaned.csv',ROOT/'data/processed/hawaii/attractions.jsonl',
             ROOT/'data/raw/corpus-webis-tripad-14.tar.gz',ROOT/'models/hawaii_bpr/metadata.json']
    before={str(p.relative_to(ROOT)):checksum(p) for p in sources}
    def all_records():
        yield from pakistan_records()
        yield from hawaii_records()
        yield from tripadvisor_records()
    result=ingest(all_records())
    if before!={str(p.relative_to(ROOT)):checksum(p) for p in sources}:
        raise RuntimeError('An existing data source changed during ingestion')
    result['source_sha256']=before
    result['country_aliases']={'United Kingdom (UK)':'United Kingdom','The Netherlands':'Netherlands'}
    (CATALOG_DIR/'coverage.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    return result


if __name__=='__main__':
    argparse.ArgumentParser(description=__doc__).parse_args()
    result=build()
    print(json.dumps({k:v for k,v in result.items() if k not in ['country_counts','country_counts_by_kind']},indent=2))
