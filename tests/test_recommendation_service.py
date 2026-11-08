"""Integration without held-out test data, synthetic ratings or weight changes."""
from dataclasses import asdict
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np

from backend.catalog import Destination, CATALOG_DIR
from backend.group_consensus import ConsensusConfig
from backend.recommendation_service import (
    RecommendationService,UserContext,GroupMember,aggregate_preference_scores,preference_scores,
)
from backend.train_baselines import ROOT,checksum


class ServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service=RecommendationService()
        cls.model=cls.service._bpr()
        cls.known=UserContext('google_local_hawaii',cls.model.users[0])

    def test_hawaii_personalization_matches_saved_hybrid(self):
        response=self.service.recommend(scope='hawaii',user=self.known)
        self.assertEqual(response['mode'],'hawaii_personalized_hybrid')
        self.assertTrue(response['personalized'])
        actual=[self.service.by_id[r['destination_id']].source_id for r in response['results']]
        self.assertEqual(actual,self.model.recommend(self.known.user_id,k=5,alpha=.75))

    def test_pakistan_routes_to_existing_tfidf(self):
        response=self.service.recommend(scope='pakistan',preferences='mountains hiking nature',user=self.known)
        self.assertFalse(response['personalized'])
        self.assertEqual(response['mode'],'pakistan_tfidf_content')
        expected=self.service._tfidf().recommend('mountains hiking nature')
        self.assertEqual([r['name'] for r in response['results']],[r['destination'] for r in expected])

    def test_other_countries_use_metadata_and_never_hawaii_factors(self):
        with patch.object(self.service,'_bpr',side_effect=AssertionError('Cross-source embedding access')):
            response=self.service.recommend(scope='catalog',country='Italy',kind='hotel',preferences='historic hotel',user=self.known)
        self.assertEqual(response['mode'],'metadata_preference')
        self.assertFalse(response['personalized'])
        self.assertTrue(response['results'])
        self.assertTrue(all(r['country']=='Italy' and r['kind']=='hotel' for r in response['results']))
        self.assertEqual(self.service.recommend(scope='catalog',country='Italy',kind='attraction',preferences='history')['status'],'no_candidates')

    def test_new_user_namespace_collision_and_empty_onboarding(self):
        app_user=UserContext('humsafar',self.known.user_id)
        with patch.object(self.service,'_bpr',side_effect=AssertionError('New user embedding access')):
            empty=self.service.recommend(scope='hawaii',user=app_user)
            fallback=self.service.recommend(scope='hawaii',user=app_user,preferences='beach hiking')
        self.assertEqual(empty['status'],'needs_preferences')
        self.assertFalse(fallback['personalized'])
        self.assertEqual(fallback['mode'],'metadata_preference')
        unknown=self.service.recommend(scope='hawaii',user=UserContext('google_local_hawaii','not-a-training-identity'),preferences='beach')
        self.assertEqual(unknown['mode'],'metadata_preference')

    def test_compatibility_flags_cannot_force_cross_source_embeddings(self):
        hotel=next(r for r in self.service.catalog if r.kind=='hotel')
        with self.assertRaises(ValueError):
            Destination.from_dict(dict(asdict(hotel),model_compatibility=['hawaii_bpr']))
        # Country equality alone never grants Google identity compatibility.
        with patch.object(self.service,'_bpr',side_effect=AssertionError('Cross-dataset personalization')):
            result=self.service.recommend(country='Pakistan',preferences='mountains',user=self.known)
        self.assertEqual(result['mode'],'metadata_preference')

    def test_bias_only_history_user_is_not_claimed_as_personalized(self):
        inactive=np.flatnonzero(~np.any(self.model.user_factors!=0,axis=1))
        self.assertEqual(len(inactive),100)
        user=UserContext('google_local_hawaii',self.model.users[inactive[0]])
        empty=self.service.recommend(scope='hawaii',user=user)
        response=self.service.recommend(scope='hawaii',user=user,preferences='beach')
        self.assertEqual(empty['status'],'needs_preferences')
        self.assertEqual(response['mode'],'metadata_preference')
        self.assertFalse(response['personalized'])
        for row in response['results']:
            self.assertNotIn(self.service.by_id[row['destination_id']].source_id,self.model.histories[user.user_id])

    def test_real_preference_groups_do_not_require_hawaii_user_ids(self):
        requests=[GroupMember('request_member_a','mountains hiking nature'),
                  GroupMember('request_member_b','lakes beautiful scenery')]
        response=self.service.recommend_group(requests,scope='pakistan')
        self.assertEqual(response['status'],'ok')
        self.assertEqual(set(response['member_modes'].values()),{'pakistan_tfidf_content'})
        self.assertTrue(response['results'])
        self.assertTrue(all(r['country']=='Pakistan' for r in response['results']))
        blocked=self.service.recommend_group([GroupMember('a'),GroupMember('b','beach')],scope='hawaii')
        self.assertEqual(blocked['status'],'needs_preferences')

    def test_mixed_history_and_new_user_group_excludes_known_history(self):
        response=self.service.recommend_group([
            GroupMember('known',user=self.known),GroupMember('new',preferences='beach hiking')],scope='hawaii')
        self.assertEqual(response['status'],'ok')
        for result in response['results']:
            source_id=self.service.by_id[result['destination_id']].source_id
            self.assertNotIn(source_id,self.model.histories[self.known.user_id])
        self.assertEqual(response['member_modes']['new'],'metadata_preference')

    def test_explicit_scores_reuse_consensus_and_reject_missing_values(self):
        records=self.service.candidates(scope='pakistan')
        # Mathematical preference-matching scores derived from genuine catalog
        # metadata and example requests; never stored as ratings/real user feedback.
        member_scores={member:{r.destination_id:float(score) for r,score in zip(records,preference_scores(query,records))}
                       for member,query in [('a','mountains hiking'),('b','lake nature')]}
        actual=self.service.group_from_scores(member_scores)
        expected=aggregate_preference_scores([r.destination_id for r in records],member_scores)
        self.assertEqual(actual,expected)
        incomplete={u:s.copy() for u,s in member_scores.items()}
        incomplete['a'].pop(next(iter(incomplete['a'])))
        with self.assertRaises(ValueError):self.service.group_from_scores(incomplete)

    def test_inference_does_not_read_heldout_or_raw_data(self):
        # Artifacts/catalog already loaded; inference must not open ANY file.
        with patch.object(Path,'open',side_effect=AssertionError('Unexpected inference file access')):
            self.service.recommend(scope='hawaii',user=self.known)
            self.service.recommend(scope='catalog',kind='hotel',country='France',preferences='historic hotel')
            self.service.recommend_group([GroupMember('a','beach'),GroupMember('b','hiking')],scope='hawaii')

    def test_existing_catalog_sources_unchanged(self):
        report=json.loads((CATALOG_DIR/'coverage.json').read_text(encoding='utf-8'))
        for name,digest in report['source_sha256'].items():
            self.assertEqual(checksum(ROOT/name),digest)


if __name__=='__main__':unittest.main()
