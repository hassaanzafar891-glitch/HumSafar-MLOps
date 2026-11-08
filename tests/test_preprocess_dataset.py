"""Tests use genuine source rows; mutations exercise validation, not new data."""

import hashlib
from pathlib import Path
import tempfile
import unittest

import pandas as pd

from backend.preprocess_dataset import ROOT, clean_dataset, preprocess


class PreprocessingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = next((ROOT / "data/raw").glob("*.csv"))
        cls.source = pd.read_csv(cls.path, dtype=str, keep_default_na=False)

    def test_real_data_preserved_and_cleaning_is_idempotent(self):
        cleaned, report = clean_dataset(self.source)
        self.assertEqual(len(cleaned), len(self.source))
        self.assertEqual(cleaned['_key'].tolist(), self.source['_key'].tolist())
        self.assertFalse(cleaned.isna().any().any())
        self.assertFalse(cleaned['_key'].duplicated().any())
        self.assertNotIn('Gilgit−Baltistan', cleaned['district'].tolist())
        self.assertIn('Gilgit-Baltistan', cleaned['district'].tolist())
        self.assertTrue(cleaned['Desc'].str.contains('Photo Credit', case=False).any())
        self.assertFalse(cleaned['recommendation_text'].str.contains('Photo Credit', case=False).any())
        self.assertEqual(report['removed_rows'], 0)
        again, _ = clean_dataset(cleaned.drop(columns='recommendation_text'))
        pd.testing.assert_frame_equal(cleaned, again)

    def test_invalid_values_fail_instead_of_dropping_rows(self):
        for column, value in [('Desc', '  \t'), ('category', ''), ('district', None),
                              ('latitude', '91'), ('longitude', '-181'),
                              ('latitude', 'NaN'), ('longitude', 'inf'), ('latitude', 'invalid')]:
            with self.subTest(column=column, value=value):
                changed = self.source.copy()
                changed.loc[0, column] = value
                with self.assertRaises(ValueError):
                    clean_dataset(changed)

    def test_identifier_collision_after_whitespace_and_case_normalization(self):
        changed = self.source.copy()
        changed.loc[1, '_key'] = ' ' + changed.loc[0, '_key'].upper() + ' '
        with self.assertRaisesRegex(ValueError, 'Duplicate destination'):
            clean_dataset(changed)

    def test_missing_schema_rejected(self):
        with self.assertRaises(ValueError):
            clean_dataset(self.source.drop(columns='Desc'))

    def test_output_roundtrip_and_raw_protection(self):
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'cleaned.csv'
            report = preprocess(self.path, output)
            reloaded = pd.read_csv(output, keep_default_na=False)
            self.assertEqual(len(reloaded), len(self.source))
            self.assertTrue(output.with_suffix('.report.json').exists())
            self.assertEqual(report['source_sha256'], before)
        for output in [self.path, ROOT / 'data/raw/cleaned.csv']:
            with self.assertRaises(ValueError):
                preprocess(self.path, output)
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), before)


if __name__ == '__main__':
    unittest.main()
