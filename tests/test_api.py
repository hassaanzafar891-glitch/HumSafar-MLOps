"""Isolated application databases and real catalog; never ML feedback/training."""
from datetime import datetime,timedelta,timezone
import hashlib
import json
from pathlib import Path
import secrets
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
import jwt
from sqlalchemy import func,select

from backend.api.app import create_app
from backend.api.config import Settings
from backend.api.database import database,initialize_schema
from backend.api.models import User,TravelGroup,Membership,MemberPreference,GroupRecommendation,Vote,ItineraryItem
from backend.recommendation_service import RecommendationService

PASSWORD='Local-API-test-password!'


class APITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.service=RecommendationService()

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='humsafar_api_test_')
        self.settings=Settings('sqlite:///'+(Path(self.temp.name)/'app.db').as_posix(),secrets.token_urlsafe(48))
        self.app=create_app(self.settings,self.service)
        self.client=TestClient(self.app)
        self.client.__enter__()
        self.actors={}

    def tearDown(self):
        self.client.__exit__(None,None,None)
        self.temp.cleanup()

    def actor(self,name):
        if name not in self.actors:
            r=self.client.post('/auth/register',json={'email':name+'@example.com','display_name':name,'password':PASSWORD})
            self.assertEqual(r.status_code,201,r.text)
            profile=r.json()
            r=self.client.post('/auth/login',data={'username':name+'@example.com','password':PASSWORD})
            self.assertEqual(r.status_code,200,r.text)
            self.actors[name]=(profile,{'Authorization':'Bearer '+r.json()['access_token']})
        return self.actors[name]

    def group(self):
        owner,oh=self.actor('owner')
        member,mh=self.actor('member')
        r=self.client.post('/groups',headers=oh,json={'name':'Integration group'})
        self.assertEqual(r.status_code,201,r.text)
        created=r.json();gid=created['group']['id']
        self.assertEqual(self.client.post('/groups/join',headers=mh,json={'invitation_code':created['invitation_code']}).status_code,200)
        return gid,owner,oh,member,mh,created['invitation_code']

    def preferences(self,gid,headers,**changes):
        body={'interests':['mountains','hiking','lakes','nature'],'preferred_countries':['Pakistan']}
        body.update(changes)
        return self.client.put(f'/groups/{gid}/preferences/me',headers=headers,json=body)

    def recommended(self):
        gid,owner,oh,member,mh,code=self.group()
        self.assertEqual(self.preferences(gid,oh).status_code,200)
        self.assertEqual(self.preferences(gid,mh).status_code,200)
        r=self.client.post(f'/groups/{gid}/recommendations',headers=oh,json={'scope':'pakistan','country':'Pakistan'})
        self.assertEqual(r.status_code,201,r.text)
        return gid,owner,oh,member,mh,r.json()

    def test_authentication_hashing_profiles_and_validation_redaction(self):
        owner,headers=self.actor('owner')
        self.assertEqual(self.client.get('/users/me').status_code,401)
        self.assertEqual(self.client.get('/users/me',headers=headers).json()['id'],owner['id'])
        with self.app.state.sessions() as db:
            stored=db.get(User,owner['id'])
            self.assertTrue(stored.password_hash.startswith('$argon2id$'))
            self.assertNotEqual(stored.password_hash,PASSWORD)
        self.assertNotIn('password_hash',owner)
        self.assertEqual(self.client.post('/auth/register',json={'email':'OWNER@example.com','display_name':'duplicate','password':PASSWORD}).status_code,409)
        bad=self.client.post('/auth/register',json={'email':'bad@example.com','display_name':'bad','password':'short'})
        self.assertEqual(bad.status_code,422)
        self.assertNotIn('"input"',bad.text)
        self.assertEqual(self.client.post('/auth/login',data={'username':'owner@example.com','password':'wrong'}).status_code,401)
        changed=self.client.patch('/users/me',headers=headers,json={'display_name':'Updated','bio':'Travel interests'})
        self.assertEqual(changed.status_code,200)
        self.assertEqual(changed.json()['display_name'],'Updated')

    def test_jwt_signature_expiry_issuer_and_logout(self):
        owner,headers=self.actor('owner')
        now=datetime.now(timezone.utc)
        payload={'sub':owner['id'],'ver':0,'iat':now-timedelta(hours=1),'exp':now-timedelta(minutes=1),
                 'jti':'test-token','iss':self.settings.jwt_issuer,'aud':self.settings.jwt_audience}
        expired=jwt.encode(payload,self.settings.jwt_secret,algorithm='HS256')
        self.assertEqual(self.client.get('/users/me',headers={'Authorization':'Bearer '+expired}).status_code,401)
        payload['exp']=now+timedelta(minutes=10)
        wrong=jwt.encode(payload,secrets.token_urlsafe(48),algorithm='HS256')
        self.assertEqual(self.client.get('/users/me',headers={'Authorization':'Bearer '+wrong}).status_code,401)
        payload['iss']='other-app'
        wrong=jwt.encode(payload,self.settings.jwt_secret,algorithm='HS256')
        self.assertEqual(self.client.get('/users/me',headers={'Authorization':'Bearer '+wrong}).status_code,401)
        self.assertEqual(self.client.post('/auth/logout',headers=headers).status_code,204)
        self.assertEqual(self.client.get('/users/me',headers=headers).status_code,401)

    def test_password_change_revokes_tokens(self):
        _,headers=self.actor('owner')
        r=self.client.post('/users/me/password',headers=headers,json={'current_password':PASSWORD,'new_password':PASSWORD+'new'})
        self.assertEqual(r.status_code,204)
        self.assertEqual(self.client.get('/users/me',headers=headers).status_code,401)
        self.assertEqual(self.client.post('/auth/login',data={'username':'owner@example.com','password':PASSWORD}).status_code,401)
        self.assertEqual(self.client.post('/auth/login',data={'username':'owner@example.com','password':PASSWORD+'new'}).status_code,200)

    def test_groups_private_membership_and_hashed_rotating_invitations(self):
        gid,owner,oh,member,mh,code=self.group()
        _,xh=self.actor('outsider')
        self.assertGreaterEqual(len(code),43)
        with self.app.state.sessions() as db:
            self.assertEqual(db.get(TravelGroup,gid).invite_digest,hashlib.sha256(code.encode()).hexdigest())
        self.assertEqual(self.client.get(f'/groups/{gid}',headers=xh).status_code,404)
        self.assertEqual(self.client.get(f'/groups/{gid}/members',headers=xh).status_code,404)
        self.assertEqual(self.client.get(f'/groups/{gid}/members',headers=mh).status_code,200)
        self.assertNotIn('invite',self.client.get(f'/groups/{gid}',headers=mh).text)
        self.assertEqual(self.client.post(f'/groups/{gid}/invitation',headers=mh).status_code,403)
        rotated=self.client.post(f'/groups/{gid}/invitation',headers=oh).json()['invitation_code']
        self.assertNotEqual(code,rotated)
        self.assertEqual(self.client.post('/groups/join',headers=xh,json={'invitation_code':code}).status_code,404)
        self.assertEqual(self.client.post('/groups/join',headers=xh,json={'invitation_code':rotated}).status_code,200)

    def test_group_management_transfer_leave_archive_and_delete(self):
        gid,owner,oh,member,mh,_=self.group()
        self.assertEqual(self.client.patch(f'/groups/{gid}',headers=mh,json={'name':'not owner'}).status_code,403)
        self.assertEqual(self.client.delete(f'/groups/{gid}/members/{owner["id"]}',headers=oh).status_code,409)
        r=self.client.post(f'/groups/{gid}/transfer-ownership',headers=oh,json={'user_id':member['id']})
        self.assertEqual(r.status_code,200,r.text)
        self.assertEqual(self.client.delete(f'/groups/{gid}/members/{owner["id"]}',headers=oh).status_code,204)
        self.assertEqual(self.client.get(f'/groups/{gid}',headers=oh).status_code,404)
        self.assertEqual(self.client.patch(f'/groups/{gid}',headers=mh,json={'archived':True}).status_code,200)
        self.assertEqual(self.preferences(gid,mh).status_code,409)
        self.assertEqual(self.client.delete(f'/groups/{gid}',headers=mh).status_code,204)

    def test_preference_permissions_and_ranges(self):
        gid,owner,oh,member,mh,_=self.group()
        _,xh=self.actor('outsider')
        self.assertEqual(self.preferences(gid,xh).status_code,404)
        self.assertEqual(self.preferences(gid,oh,user_id=member['id']).status_code,422)
        self.assertEqual(self.preferences(gid,oh,budget_min=200,budget_max=10,currency='USD').status_code,422)
        self.assertEqual(self.preferences(gid,oh,budget_min=10).status_code,422)
        self.assertEqual(self.preferences(gid,oh,start_date='2030-06-10',end_date='2030-06-01').status_code,422)
        self.assertEqual(self.preferences(gid,oh,preferred_destination_ids=['not-a-catalog-id']).status_code,422)
        self.assertEqual(self.preferences(gid,oh).status_code,200)
        self.assertEqual(self.client.get(f'/groups/{gid}/preferences/me',headers=mh).status_code,404)

    def test_recommendations_require_all_preferences_and_report_unsupported_filters(self):
        gid,owner,oh,member,mh,_=self.group()
        self.assertEqual(self.preferences(gid,oh).status_code,200)
        endpoint=f'/groups/{gid}/recommendations'
        self.assertEqual(self.client.post(endpoint,headers=oh,json={'scope':'pakistan'}).status_code,409)
        self.assertEqual(self.preferences(gid,mh,budget_min=100,budget_max=500,currency='USD',start_date='2030-06-01',end_date='2030-06-10').status_code,200)
        r=self.client.post(endpoint,headers=mh,json={'scope':'pakistan'})
        self.assertEqual(r.status_code,201,r.text)
        result=r.json()
        self.assertTrue(result['payload']['results'])
        self.assertEqual(set(result['payload']['member_modes'].values()),{'pakistan_tfidf_content'})
        self.assertTrue({'budget_filter_unsupported','date_availability_unsupported'}<={w['code'] for w in result['warnings']})
        self.assertTrue(all(i['country']=='Pakistan' for i in result['payload']['results']))
        self.assertEqual(self.client.get(f'/groups/{gid}/recommendations',headers=oh).status_code,200)

    def test_geographic_and_selected_destination_constraints(self):
        gid,_,oh,_,mh,_=self.group()
        self.assertEqual(self.preferences(gid,oh).status_code,200)
        self.assertEqual(self.preferences(gid,mh,preferred_countries=['United States']).status_code,200)
        self.assertEqual(self.client.post(f'/groups/{gid}/recommendations',headers=oh,json={'scope':'catalog'}).status_code,409)
        ids=[r.destination_id for r in self.service.catalog if r.data_source=='pakistan_tourism' and 'Lake' in r.categories][:2]
        for h in [oh,mh]:
            self.assertEqual(self.preferences(gid,h,preferred_destination_ids=ids,interests=['lake']).status_code,200)
        r=self.client.post(f'/groups/{gid}/recommendations',headers=oh,json={'scope':'pakistan'})
        self.assertEqual(r.status_code,201,r.text)
        self.assertTrue(set(i['destination_id'] for i in r.json()['payload']['results'])<=set(ids))

    def test_new_application_users_never_receive_historical_embeddings(self):
        gid,_,oh,_,mh,_=self.group()
        for h in [oh,mh]:self.assertEqual(self.preferences(gid,h,preferred_countries=['United States'],interests=['beach','hiking']).status_code,200)
        with patch.object(self.service,'_bpr',side_effect=AssertionError('Historical identity access')):
            r=self.client.post(f'/groups/{gid}/recommendations',headers=oh,json={'scope':'hawaii'})
        self.assertEqual(r.status_code,201,r.text)
        self.assertEqual(set(r.json()['payload']['member_modes'].values()),{'metadata_preference'})
        self.assertEqual(self.client.post(f'/groups/{gid}/recommendations',headers=oh,json={'scope':'hawaii','user_id':'historical-id'}).status_code,422)

    def test_voting_is_own_only_unique_and_requires_recommended_destination(self):
        gid,_,oh,member,mh,rec=self.recommended()
        _,xh=self.actor('outsider')
        endpoint=f'/groups/{gid}/recommendations/{rec["id"]}/vote'
        first,second=[r['destination_id'] for r in rec['payload']['results'][:2]]
        self.assertEqual(self.client.put(endpoint,headers=xh,json={'destination_id':first}).status_code,404)
        self.assertEqual(self.client.put(endpoint,headers=oh,json={'destination_id':first,'user_id':member['id']}).status_code,422)
        self.assertEqual(self.client.put(endpoint,headers=oh,json={'destination_id':'not-a-recommendation'}).status_code,422)
        self.assertEqual(self.client.put(endpoint,headers=oh,json={'destination_id':first}).status_code,200)
        self.assertEqual(self.client.put(endpoint,headers=oh,json={'destination_id':second}).status_code,200)
        self.assertEqual(self.client.put(endpoint,headers=mh,json={'destination_id':second}).status_code,200)
        counts=self.client.get(endpoint+'s',headers=mh).json()
        self.assertEqual(sum(r['votes'] for r in counts),2)
        self.assertEqual(self.client.delete(endpoint,headers=oh).status_code,204)
        self.assertEqual(sum(r['votes'] for r in self.client.get(endpoint+'s',headers=mh).json()),1)

    def test_preferences_changes_make_recommendations_stale(self):
        gid,_,oh,_,mh,rec=self.recommended()
        self.assertEqual(self.preferences(gid,mh,interests=['history']).status_code,200)
        item=rec['payload']['results'][0]['destination_id']
        self.assertEqual(self.client.put(f'/groups/{gid}/recommendations/{rec["id"]}/vote',headers=oh,json={'destination_id':item}).status_code,409)
        self.assertFalse(self.client.get(f'/groups/{gid}/recommendations/{rec["id"]}',headers=oh).json()['is_current'])
        self.assertEqual(self.client.post(f'/groups/{gid}/itinerary',headers=oh,json={'recommendation_id':rec['id'],'destination_id':item,'position':1}).status_code,409)

    def test_itinerary_owner_permissions_date_window_and_persistence(self):
        gid,_,oh,_,mh,_=self.group()
        for h in [oh,mh]:self.assertEqual(self.preferences(gid,h,start_date='2030-06-01',end_date='2030-06-10').status_code,200)
        rec=self.client.post(f'/groups/{gid}/recommendations',headers=oh,json={'scope':'pakistan'}).json()
        body={'recommendation_id':rec['id'],'destination_id':rec['payload']['results'][0]['destination_id'],'position':1,'planned_date':'2030-06-02','notes':'Member-selected plan; not a booking'}
        endpoint=f'/groups/{gid}/itinerary'
        self.assertEqual(self.client.post(endpoint,headers=mh,json=body).status_code,403)
        self.assertEqual(self.client.post(endpoint,headers=oh,json=dict(body,planned_date='2030-07-01')).status_code,409)
        r=self.client.post(endpoint,headers=oh,json=body);self.assertEqual(r.status_code,201,r.text)
        item=r.json()
        self.assertEqual(self.client.post(endpoint,headers=oh,json=body).status_code,409)
        self.assertEqual(self.client.get(endpoint,headers=mh).json()[0]['id'],item['id'])
        self.assertEqual(self.client.patch(endpoint+'/'+item['id'],headers=oh,json={'position':2,'notes':'updated'}).status_code,200)
        # A separate API instance opens the SAME file database and validates the
        # existing schema; data is not merely held in in-memory route objects.
        with TestClient(create_app(self.settings,self.service)) as other:
            self.assertEqual(other.get(endpoint,headers=oh).json()[0]['position'],2)
        self.assertEqual(self.client.delete(endpoint+'/'+item['id'],headers=oh).status_code,204)

    def test_cross_group_object_ids_and_removed_members_are_denied(self):
        gid,_,oh,member,mh,rec=self.recommended()
        other=self.client.post('/groups',headers=mh,json={'name':'Other group'}).json()['group']['id']
        self.assertEqual(self.client.get(f'/groups/{other}/recommendations/{rec["id"]}',headers=mh).status_code,404)
        self.assertEqual(self.client.delete(f'/groups/{gid}/members/{member["id"]}',headers=oh).status_code,204)
        self.assertEqual(self.client.get(f'/groups/{gid}/recommendations',headers=mh).status_code,404)

    def test_group_delete_cascades_application_records(self):
        gid,_,oh,_,mh,rec=self.recommended()
        item=rec['payload']['results'][0]['destination_id']
        self.client.put(f'/groups/{gid}/recommendations/{rec["id"]}/vote',headers=mh,json={'destination_id':item})
        self.client.post(f'/groups/{gid}/itinerary',headers=oh,json={'recommendation_id':rec['id'],'destination_id':item,'position':1})
        self.assertEqual(self.client.delete(f'/groups/{gid}',headers=oh).status_code,204)
        with self.app.state.sessions() as db:
            for table in [Membership,MemberPreference,GroupRecommendation,Vote,ItineraryItem]:
                self.assertEqual(db.scalar(select(func.count()).select_from(table).where(table.group_id==gid)),0)

    def test_individual_recommendation_openapi_and_no_test_access(self):
        gid,_,oh,_,mh,_=self.group();self.preferences(gid,oh)
        original=Path.open
        def guarded(path,*args,**kwargs):
            if path.name=='test.csv':raise AssertionError('Held-out test split access')
            return original(path,*args,**kwargs)
        with patch.object(Path,'open',guarded):
            r=self.client.post(f'/groups/{gid}/recommendations/individual',headers=oh,json={'scope':'pakistan'})
        self.assertEqual(r.status_code,201,r.text)
        self.assertEqual(r.json()['payload']['mode'],'pakistan_tfidf_content')
        rec=r.json()
        destination=rec['payload']['results'][0]['destination_id']
        self.assertEqual(self.client.put(f'/groups/{gid}/recommendations/{rec["id"]}/vote',headers=oh,
            json={'destination_id':destination}).status_code,409)
        self.assertEqual(self.client.post(f'/groups/{gid}/itinerary',headers=oh,
            json={'recommendation_id':rec['id'],'destination_id':destination,'position':1}).status_code,409)
        spec=self.client.get('/openapi.json').json()
        self.assertIn('OAuth2PasswordBearer',spec['components']['securitySchemes'])
        self.assertEqual(self.client.get('/docs').status_code,200)

    def test_schema_init_reproducible_and_login_limiter(self):
        initialize_schema(self.app.state.engine)
        for _ in range(20):
            r=self.client.post('/auth/login',data={'username':'none@example.com','password':'wrong'})
            self.assertEqual(r.status_code,401)
        self.assertEqual(self.client.post('/auth/login',data={'username':'none@example.com','password':'wrong'}).status_code,429)

    def test_removal_invalidates_old_invitation_and_catalog_responses(self):
        gid,_,oh,member,mh,code=self.group()
        self.assertEqual(self.client.delete(f'/groups/{gid}/members/{member["id"]}',headers=oh).status_code,204)
        self.assertEqual(self.client.post('/groups/join',headers=mh,json={'invitation_code':code}).status_code,404)
        page=self.client.get('/catalog',params={'country':'Pakistan','kind':'attraction','limit':2})
        self.assertEqual(page.status_code,200)
        self.assertEqual(page.json()['total'],69)
        self.assertEqual(len(page.json()['items']),2)
        self.assertEqual(self.client.get('/catalog/coverage').json()['total_source_listings'],13625)


if __name__=='__main__':unittest.main()
