"""Validate actual source-derived catalog rows; mutations are error fixtures."""
from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import unittest

from backend.catalog import CATALOG_DIR, Destination, coverage, country_mapping, ingest, load_catalog, stable_id
from backend.train_baselines import checksum


class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows=load_catalog()
        cls.report=json.loads((CATALOG_DIR/'coverage.json').read_text(encoding='utf-8'))

    def test_all_real_catalog_rows_validate(self):
        self.assertEqual(len(self.rows),13625)
        for row in self.rows:
            self.assertEqual(Destination.from_dict(asdict(row)),row)
            self.assertEqual(row.destination_id,stable_id(row.data_source,row.source_id))
        self.assertEqual(len({row.destination_id for row in self.rows}),len(self.rows))

    def test_schema_rejects_invalid_coordinates_missing_fields_and_modes(self):
        original=asdict(self.rows[0])
        for field,value in [('latitude',91),('longitude',float('nan')),('categories','Beach'),('name',''),
                            ('country','Caribbean'),('model_compatibility',['worldwide_bpr'])]:
            with self.subTest(field=field),self.assertRaises(ValueError):
                Destination.from_dict(dict(original,**{field:value}))
        changed=original.copy()
        del changed['country']
        with self.assertRaises(ValueError):Destination.from_dict(changed)

    def test_source_country_mappings_and_scope_flags(self):
        self.assertEqual(country_mapping('United Kingdom (UK)'),'United Kingdom')
        self.assertEqual(country_mapping('The Netherlands'),'Netherlands')
        self.assertIsNone(country_mapping('Caribbean'))
        self.assertIsNone(country_mapping(None))
        caribbean=0
        for row in self.rows:
            if row.data_source=='pakistan_tourism':
                self.assertEqual(row.country,'Pakistan')
                self.assertIn('pakistan_tfidf',row.model_compatibility)
            elif row.data_source=='google_local_hawaii':
                self.assertEqual((row.country,row.city_or_region),('United States','Hawaii'))
                self.assertIn('hawaii_bpr',row.model_compatibility)
            else:
                self.assertEqual(row.kind,'hotel')
                self.assertNotIn('hawaii_bpr',row.model_compatibility)
                if row.provenance['original_country_label']=='Caribbean':
                    caribbean+=1
                    self.assertIsNone(row.country)
        self.assertEqual(caribbean,342)

    def test_duplicates_collapse_or_fail_without_overwriting(self):
        row=self.rows[0]
        with tempfile.TemporaryDirectory() as directory:
            result=ingest([row,row],directory)
            self.assertEqual(result['total_source_listings'],1)
            self.assertEqual(result['exact_duplicate_rows_collapsed'],1)
            output=Path(directory)/'catalog.jsonl'
            before=checksum(output)
            conflict=Destination.from_dict(dict(asdict(row),name=row.name+' [conflict fixture]'))
            with self.assertRaisesRegex(ValueError,'Conflicting duplicate'):
                ingest([row,conflict],directory)
            self.assertEqual(checksum(output),before)

    def test_coverage_does_not_equate_hotels_with_attractions(self):
        actual=coverage(self.rows)
        self.assertEqual(actual['source_counts'],self.report['source_counts'])
        self.assertEqual(actual['named_country_or_territory_labels'],117)
        self.assertEqual(actual['unknown_country_listings'],726)
        self.assertEqual(actual['country_counts_by_kind']['attraction'],{'Pakistan':69,'United States':1512})
        self.assertEqual(actual['model_compatibility_counts']['hawaii_bpr'],1512)
        self.assertEqual(sum(actual['country_counts'].values())+726,13625)


if __name__=='__main__':unittest.main()
