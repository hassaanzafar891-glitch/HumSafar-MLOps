"""Data-free CI: public metadata subset, isolated API users and math fixtures.

No trained weights, raw datasets, real interaction histories or test split needed.
"""
from dataclasses import asdict
import json
import os
from pathlib import Path
import secrets
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from fastapi.testclient import TestClient
import yaml

from backend.api.app import create_app
from backend.api.config import Settings
from backend.catalog import Destination,ingest,coverage
from backend.group_consensus import aggregate,form_groups,satisfaction,ConsensusConfig
from backend.mlops.definitions import ROOT,pipeline_document,validate_layout
from backend.mlops.pipeline import execute
from backend.mlops.quality import metric_check
from backend.mlops.registry import approve
from backend.recommendation_service import RecommendationService,UserContext,GroupMember

FIXTURE=ROOT/'tests/fixtures/catalog_public.json'


class PortableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows=[Destination.from_dict(row) for row in json.loads(FIXTURE.read_text(encoding='utf-8'))]

    def test_schema_duplicates_coverage_and_no_cross_dataset_personalization(self):
        self.assertEqual(len(self.rows),5)
        report=coverage(self.rows)
        self.assertEqual(report['country_counts'],{'Italy':1,'Pakistan':2,'United States':2})
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(ingest([self.rows[0],self.rows[0]],directory)['exact_duplicate_rows_collapsed'],1)
        with self.assertRaises(ValueError):Destination.from_dict(dict(asdict(self.rows[0]),latitude=100))
        service=RecommendationService(self.rows)
        with patch.object(service,'_bpr',side_effect=AssertionError('Cross-dataset model access')):
            r=service.recommend(scope='catalog',kind='hotel',country='Italy',preferences='hotel',user=UserContext('google_local_hawaii','mock-only-identity'))
            self.assertFalse(r['personalized'])
            self.assertEqual(r['mode'],'metadata_preference')
            self.assertEqual(service.recommend(scope='hawaii')['status'],'needs_preferences')

    def test_group_math_reproducibility_and_complete_preferences(self):
        # These are mathematical utility inputs, not fabricated rating records.
        scores=np.array([[.9,.3,.6],[.2,.8,.6]])
        self.assertEqual(aggregate(scores,'average',ConsensusConfig(top_k=1)).tolist(),[2])
        self.assertEqual(aggregate(scores,'least_misery',ConsensusConfig(top_k=1)).tolist(),[2])
        self.assertEqual(aggregate(scores,'adaptive_consensus',ConsensusConfig(top_k=1)).tolist(),[2])
        self.assertAlmostEqual(satisfaction(np.array([.2,.8]))['disparity_range'],.6)
        ids=['mock-a','mock-b','mock-c','mock-d']
        self.assertEqual(form_groups(ids,2,count=3),form_groups(ids,2,count=3))

    def test_pipeline_layout_and_execution_gate(self):
        document=yaml.safe_load((ROOT/'dvc.yaml').read_text(encoding='utf-8'))
        graph=validate_layout(document)
        self.assertIn('bpr',graph['groups'])
        self.assertIn('prepare',graph['catalog'])
        self.assertEqual(document['stages'],pipeline_document()['stages'])
        with patch.dict(os.environ,{'HUMSAFAR_ALLOW_PIPELINE_EXECUTION':'0'}):
            with self.assertRaisesRegex(RuntimeError,'Rebuild blocked'):execute('bpr')

    def test_metric_accounting_and_promotion_guard(self):
        metric_check({'recall_at_10':.5,'ndcg_at_10':.4,'hit_users':2,'eligible_users':4},4)
        with self.assertRaises(ValueError):metric_check({'recall_at_10':.5,'ndcg_at_10':.8,'hit_users':2,'eligible_users':4},4)
        with tempfile.TemporaryDirectory() as directory:
            candidate=Path(directory)/'candidate.json';approval=Path(directory)/'approval.json'
            candidate.write_text('{"objective":"ranking"}',encoding='utf-8')
            approval.write_text('{"approved":false}',encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'approval required'):approve(candidate,approval,Path(directory)/'output.json')


class PortableAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service=RecommendationService([Destination.from_dict(row) for row in json.loads(FIXTURE.read_text(encoding='utf-8'))])

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.app=create_app(Settings('sqlite:///'+(Path(self.temp.name)/'ci.db').as_posix(),secrets.token_urlsafe(48)),self.service)
        self.client=TestClient(self.app);self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None,None,None);self.temp.cleanup()

    def actor(self,name):
        r=self.client.post('/auth/register',json={'email':name+'@example.com','display_name':name,'password':'CI-fixture-password-only!'})
        self.assertEqual(r.status_code,201,r.text)
        login=self.client.post('/auth/login',data={'username':name+'@example.com','password':'CI-fixture-password-only!'})
        self.assertEqual(login.status_code,200)
        return {'Authorization':'Bearer '+login.json()['access_token']}

    def test_isolated_api_workflow_and_permissions(self):
        owner,member,outsider=[self.actor(name) for name in ['ci-owner','ci-member','ci-outsider']]
        created=self.client.post('/groups',headers=owner,json={'name':'CI isolated fixture'}).json()
        gid=created['group']['id']
        self.assertEqual(self.client.get('/groups/'+gid,headers=outsider).status_code,404)
        self.assertEqual(self.client.post('/groups/join',headers=member,json={'invitation_code':created['invitation_code']}).status_code,200)
        for headers in [owner,member]:
            r=self.client.put(f'/groups/{gid}/preferences/me',headers=headers,json={'interests':['Mountainous'],'preferred_countries':['Pakistan']})
            self.assertEqual(r.status_code,200,r.text)
        generated=self.client.post(f'/groups/{gid}/recommendations',headers=owner,json={'scope':'catalog','country':'Pakistan'})
        self.assertEqual(generated.status_code,201,generated.text)
        rec=generated.json();dest=rec['payload']['results'][0]['destination_id']
        route=f'/groups/{gid}/recommendations/{rec["id"]}/vote'
        self.assertEqual(self.client.put(route,headers=member,json={'destination_id':dest}).status_code,200)
        self.assertEqual(self.client.put(route,headers=outsider,json={'destination_id':dest}).status_code,404)
        body={'recommendation_id':rec['id'],'destination_id':dest,'position':1}
        self.assertEqual(self.client.post(f'/groups/{gid}/itinerary',headers=member,json=body).status_code,403)
        self.assertEqual(self.client.post(f'/groups/{gid}/itinerary',headers=owner,json=body).status_code,201)
        self.assertEqual(len(self.client.get(f'/groups/{gid}/itinerary',headers=member).json()),1)
        self.assertEqual(self.client.post('/auth/logout',headers=owner).status_code,204)
        self.assertEqual(self.client.get('/users/me',headers=owner).status_code,401)
