"""Versioned, source-scoped international catalog ingestion and validation."""
from collections import Counter
import csv
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
import tempfile

ROOT=Path(__file__).resolve().parents[1]
CATALOG_DIR=ROOT/'data/processed/international'
COUNTRY_ALIASES={'United Kingdom (UK)':'United Kingdom','The Netherlands':'Netherlands'}
NON_COUNTRY_LABELS={'Caribbean'}
MODES={'metadata_preference','pakistan_tfidf','hawaii_bpr'}


def stable_id(source,source_id):
    return source+':'+hashlib.sha256(source_id.encode('utf-8')).hexdigest()


def country_mapping(label):
    label=label.strip() if isinstance(label,str) else ''
    return None if not label or label in NON_COUNTRY_LABELS else COUNTRY_ALIASES.get(label,label)


@dataclass
class Destination:
    schema_version: int
    destination_id: str
    name: str
    kind: str
    country: str | None
    city_or_region: str | None
    latitude: float | None
    longitude: float | None
    categories: list[str]
    description: str | None
    address: str | None
    data_source: str
    source_id: str
    geographic_coverage: str
    model_compatibility: list[str]
    provenance: dict

    def validate(self):
        if self.schema_version!=1:
            raise ValueError('Unsupported catalog schema_version')
        for key in ['destination_id','name','data_source','source_id','geographic_coverage']:
            value=getattr(self,key)
            if not isinstance(value,str) or not value.strip():
                raise ValueError(f'{key} must be a nonblank string')
        if self.destination_id!=stable_id(self.data_source,self.source_id):
            raise ValueError('Destination ID must match its stable source-scoped identity')
        if self.kind not in ['attraction','hotel']:
            raise ValueError('kind must be attraction or hotel')
        for key in ['country','city_or_region','description','address']:
            value=getattr(self,key)
            if value is not None and (not isinstance(value,str) or not value.strip()):
                raise ValueError(f'{key} must be nonblank or null')
        if self.country in NON_COUNTRY_LABELS:
            raise ValueError('A regional label cannot be treated as a country')
        for key,limit in [('latitude',90),('longitude',180)]:
            value=getattr(self,key)
            if value is not None and (isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not -limit<=value<=limit):
                raise ValueError(f'Invalid {key}')
        if not isinstance(self.categories,list) or any(not isinstance(c,str) or not c.strip() for c in self.categories):
            raise ValueError('categories must be a list of genuine nonblank source labels')
        if len(self.categories)!=len(set(self.categories)):
            raise ValueError('Duplicate category labels')
        if not isinstance(self.provenance,dict) or not isinstance(self.provenance.get('country_basis'),str) or not self.provenance['country_basis'].strip():
            raise ValueError('Country mapping provenance is required')
        if not isinstance(self.model_compatibility,list) or not set(self.model_compatibility)<=MODES:
            raise ValueError('Invalid model compatibility flags')
        if len(self.model_compatibility)!=len(set(self.model_compatibility)):
            raise ValueError('Duplicate model compatibility flags')
        if 'hawaii_bpr' in self.model_compatibility and not (self.data_source=='google_local_hawaii' and self.country=='United States' and self.kind=='attraction'):
            raise ValueError('Hawaii BPR cannot be assigned to unrelated sources')
        if 'pakistan_tfidf' in self.model_compatibility and not (self.data_source=='pakistan_tourism' and self.country=='Pakistan' and self.kind=='attraction'):
            raise ValueError('Pakistan TF-IDF cannot be assigned to unrelated sources')
        return self

    @classmethod
    def from_dict(cls,record):
        try:
            return cls(**record).validate()
        except TypeError as exc:
            raise ValueError(f'Catalog schema fields mismatch: {exc}') from exc


def coverage(records):
    country_counts=Counter(r.country for r in records if r.country)
    by_kind={kind:dict(sorted(Counter(r.country or '__unknown__' for r in records if r.kind==kind).items())) for kind in ['attraction','hotel']}
    return {'total_source_listings':len(records),'named_country_or_territory_labels':len(country_counts),
            'country_counts':dict(sorted(country_counts.items())),
            'country_counts_by_kind':by_kind,
            'unknown_country_listings':sum(r.country is None for r in records),
            'source_counts':dict(Counter(r.data_source for r in records)),
            'model_compatibility_counts':{mode:sum(mode in r.model_compatibility for r in records) for mode in sorted(MODES)},
            'missing_coordinates':sum(r.latitude is None or r.longitude is None for r in records),
            'missing_descriptions':sum(r.description is None for r in records),
            'notes':['Counts are source listings, not resolved unique physical entities. No fuzzy cross-source merges.',
                     'Country labels include territories and historical source labels; they are not a verified current sovereign-country list.',
                     'International hotel metadata coverage does not imply international attraction personalization. Hawaii BPR is source-ID- and user-namespace-bound.',
                     'Unknown countries remain null; Caribbean is kept as a source regional label, not a country.']}


def ingest(records,output_dir=CATALOG_DIR):
    """Any new source can emit the same Destination schema; conflicts fail closed."""
    output_dir=Path(output_dir)
    if output_dir.resolve().is_relative_to((ROOT/'data/raw').resolve()):
        raise ValueError('Catalog output cannot overwrite raw data')
    unique={}
    exact_duplicates=0
    for record in records:
        record=record.validate() if isinstance(record,Destination) else Destination.from_dict(record)
        previous=unique.get(record.destination_id)
        if previous is not None:
            if asdict(previous)!=asdict(record):
                raise ValueError(f'Conflicting duplicate destination: {record.destination_id}')
            exact_duplicates+=1
        else:
            unique[record.destination_id]=record
    ordered=sorted(unique.values(),key=lambda r:r.destination_id)
    report=dict(coverage(ordered),exact_duplicate_rows_collapsed=exact_duplicates)
    output_dir.mkdir(parents=True,exist_ok=True)
    # Validate the entire input before replacing any previous catalog output.
    with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=output_dir,delete=False,suffix='.jsonl') as stream:
        temporary=Path(stream.name)
        for record in ordered:
            stream.write(json.dumps(asdict(record),ensure_ascii=False)+'\n')
    temporary.replace(output_dir/'catalog.jsonl')
    write_catalog_metadata(output_dir,report)
    return report


def write_catalog_metadata(output_dir,report):
    """Machine-readable schema and complete country-by-kind coverage table."""
    output_dir=Path(output_dir)
    nullable=lambda kind:{'type':[kind,'null']}
    props={key:{'type':'string','minLength':1} for key in ['destination_id','name','data_source','source_id','geographic_coverage']}
    props.update(schema_version={'const':1},kind={'enum':['attraction','hotel']},
                 country=nullable('string'),city_or_region=nullable('string'),
                 latitude=dict(nullable('number'),minimum=-90,maximum=90),
                 longitude=dict(nullable('number'),minimum=-180,maximum=180),
                 categories={'type':'array','items':{'type':'string','minLength':1},'uniqueItems':True},
                 description=nullable('string'),address=nullable('string'),
                 model_compatibility={'type':'array','items':{'enum':sorted(MODES)},'uniqueItems':True},
                 provenance={'type':'object','required':['country_basis'],'properties':{'country_basis':{'type':'string','minLength':1}}})
    schema={'$schema':'https://json-schema.org/draft/2020-12/schema','title':'HumSafar destination catalog v1',
            'type':'object','required':list(Destination.__dataclass_fields__),'additionalProperties':False,'properties':props,
            '$comment':'Destination.validate additionally enforces stable source IDs, finite coordinates, non-country label handling and source/model compatibility boundaries.'}
    (output_dir/'schema.json').write_text(json.dumps(schema,indent=2)+'\n',encoding='utf-8')
    (output_dir/'coverage.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    with (output_dir/'coverage_by_country.csv').open('w',encoding='utf-8',newline='') as stream:
        writer=csv.writer(stream)
        writer.writerow(['source_country_or_territory_label','attractions','hotels','total_listings'])
        for country in sorted(set(report['country_counts'])|{'__unknown__'}):
            a=report['country_counts_by_kind']['attraction'].get(country,0)
            h=report['country_counts_by_kind']['hotel'].get(country,0)
            writer.writerow([country,a,h,a+h])


def load_catalog(path=CATALOG_DIR/'catalog.jsonl'):
    with Path(path).open(encoding='utf-8') as stream:
        rows=[Destination.from_dict(json.loads(line)) for line in stream if line.strip()]
    if len({r.destination_id for r in rows})!=len(rows):
        raise ValueError('Duplicate destination IDs in catalog')
    return rows
