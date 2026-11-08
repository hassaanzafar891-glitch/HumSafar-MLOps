"""Private group coordination; fixtures never become recommendation data."""
from datetime import date
import unittest
from unittest.mock import patch
import numpy as np
import test_api as api_tests
from backend.api.planning import availability
from backend.api.schemas import Preferences
from backend.api.recommendations import PlanningService
from backend.recommendation_service import RecommendationService,UserContext


class AvailabilityTests(unittest.TestCase):
    def test_inclusive_overlap_missing_and_conflict(self):
        a=Preferences(start_date='2030-06-01',end_date='2030-06-10')
        b=Preferences(start_date='2030-06-10',end_date='2030-06-20')
        result=availability(['a','b'],{'a':a,'b':b})
        self.assertEqual(result['status'],'overlap')
        self.assertEqual(result['start_date'],date(2030,6,10))
        self.assertEqual(result['end_date'],date(2030,6,10))
        self.assertEqual(availability(['a','b'],{'a':a})['status'],'incomplete')
        self.assertEqual(availability(['a'],{})['status'],'unknown')
        b.start_date=date(2030,6,11)
        self.assertEqual(availability(['a','b'],{'a':a,'b':b})['status'],'conflict')


class PlanningTests(unittest.TestCase):
    # Reuse isolation/helpers without inheriting the existing test cases.
    setUpClass=classmethod(api_tests.APITests.setUpClass.__func__)
    setUp=api_tests.APITests.setUp
    tearDown=api_tests.APITests.tearDown
    actor=api_tests.APITests.actor
    group=api_tests.APITests.group
    preferences=api_tests.APITests.preferences
    recommended=api_tests.APITests.recommended

    def test_flexible_scoring_preserves_mode_and_does_not_load_embeddings(self):
        records=[self.service.candidates(country='Pakistan')[0],
                 self.service.candidates(country='United States')[0]]
        adapter=PlanningService(records,{'app-user':Preferences(preferred_countries=['Pakistan'],country_requirement='preferred')})
        with patch.object(RecommendationService,'_scores',return_value=(np.array([.4,.6]),'metadata_preference',False)),patch.object(adapter,'_bpr',side_effect=AssertionError('No historical identity')):
            values,mode,personalized=adapter._scores(records,'catalog','nature',UserContext('humsafar','app-user'))
        np.testing.assert_allclose(values,[.49,.51])
        self.assertEqual(mode,'metadata_preference')
        self.assertFalse(personalized)

    def test_selected_attraction_restrictions_remain_mandatory(self):
        gid,_,oh,_,mh,_=self.group()
        ids=[r.destination_id for r in self.service.candidates(country='Pakistan')[:2]]
        self.preferences(gid,oh,preferred_destination_ids=[ids[0]])
        self.preferences(gid,mh,preferred_destination_ids=[ids[1]])
        path=f'/groups/{gid}'
        plan=self.client.get(path+'/planning',headers=oh).json()
        self.assertEqual(plan['country_status'],'mandatory_conflict')
        self.assertEqual(plan['candidate_count'],0)
        self.preferences(gid,mh,preferred_destination_ids=[ids[1]],destination_requirement='preferred')
        self.assertEqual(self.client.get(path+'/planning',headers=oh).json()['candidate_count'],1)
        # A single compatible record is not guaranteed to contain an interest
        # match. Check filtering itself without inventing recommendation signal.

    def test_legacy_mandatory_and_flexible_countries(self):
        gid,_,oh,_,mh,_=self.group()
        self.preferences(gid,oh)
        self.preferences(gid,mh,preferred_countries=['United States'])
        path=f'/groups/{gid}'
        plan=self.client.get(path+'/planning',headers=oh).json()
        self.assertEqual(plan['country_status'],'mandatory_conflict')
        self.assertEqual(plan['candidate_count'],0)
        self.assertEqual(self.client.post(path+'/recommendations',headers=oh,json={'scope':'catalog'}).status_code,409)
        self.preferences(gid,mh,preferred_countries=['United States'],country_requirement='preferred')
        plan=self.client.get(path+'/planning',headers=oh).json()
        self.assertEqual(set(plan['compatible_countries']),{'Pakistan'})
        response=self.client.post(path+'/recommendations',headers=oh,json={'scope':'catalog'})
        self.assertEqual(response.status_code,201,response.text)
        self.assertTrue(all(r['country']=='Pakistan' for r in response.json()['payload']['results']))
        self.preferences(gid,oh,country_requirement='preferred')
        plan=self.client.get(path+'/planning',headers=mh).json()
        self.assertEqual(plan['country_status'],'different_preferences')
        self.assertEqual(set(plan['compatible_countries']),{'Pakistan','United States'})
        self.assertEqual(plan['candidate_count'],1581)
        self.assertEqual(self.client.post(path+'/recommendations',headers=oh,json={'scope':'catalog'}).status_code,201)
        outsider=self.actor('outsider')[1]
        self.assertEqual(self.client.get(path+'/planning',headers=outsider).status_code,404)
        self.assertNotIn('budget_min',str(plan['members']))

    def test_dates_votes_and_itinerary_are_separate(self):
        gid,owner,oh,member,mh,_=self.group()
        self.preferences(gid,oh,start_date='2030-06-01',end_date='2030-06-10')
        self.preferences(gid,mh,start_date='2030-06-03',end_date='2030-06-08')
        path=f'/groups/{gid}'
        plan=self.client.get(path+'/planning',headers=oh).json()
        self.assertEqual(plan['availability']['start_date'],'2030-06-03')
        self.assertEqual(plan['availability']['end_date'],'2030-06-08')
        run=self.client.post(path+'/recommendations',headers=oh,json={'scope':'pakistan'}).json()
        recpath=path+'/recommendations/'+run['id']
        ids=[r['destination_id'] for r in run['payload']['results']]
        self.client.put(recpath+'/vote',headers=oh,json={'destination_id':ids[0]})
        self.client.put(recpath+'/vote',headers=mh,json={'destination_id':ids[1]})
        board=self.client.get(recpath+'/voting',headers=oh).json()
        self.assertEqual(board['total_votes'],2)
        self.assertEqual(board['own_destination_id'],ids[0])
        self.assertEqual({m['display_name'] for m in board['members']},{'owner','member'})
        self.assertEqual(self.client.get(path+'/itinerary',headers=oh).json(),[])
        self.client.put(recpath+'/vote',headers=mh,json={'destination_id':ids[0]})
        self.assertEqual(self.client.get(recpath+'/voting',headers=mh).json()['choices'][0]['votes'],2)
        self.client.delete(recpath+'/vote',headers=mh)
        self.assertIsNone(self.client.get(recpath+'/voting',headers=mh).json()['own_destination_id'])
        body={'recommendation_id':run['id'],'destination_id':ids[0],'position':1,'planned_date':'2030-06-02'}
        self.assertEqual(self.client.post(path+'/itinerary',headers=oh,json=body).status_code,409)
        body['planned_date']='2030-06-03'
        self.assertEqual(self.client.post(path+'/itinerary',headers=oh,json=body).status_code,201)
        self.assertEqual(self.client.post(path+'/itinerary',headers=mh,json=body).status_code,403)
        self.preferences(gid,mh,start_date='2030-07-01',end_date='2030-07-10')
        self.assertEqual(self.client.get(path+'/planning',headers=oh).json()['availability']['status'],'conflict')
        self.assertFalse(self.client.get(recpath+'/voting',headers=oh).json()['eligible_to_vote'])
        outsider=self.actor('outsider')[1]
        self.assertEqual(self.client.get(recpath+'/voting',headers=outsider).status_code,404)
