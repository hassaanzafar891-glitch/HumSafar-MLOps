"""Exercise real ASGI endpoints and a temporary persistent SQLite database.

Example accounts and actions are explicitly demo fixtures, never model feedback.
No passwords, tokens or invitation codes are written to the transcript.
"""
import json
from pathlib import Path
import secrets
import tempfile

from fastapi.testclient import TestClient

from backend.api.app import create_app
from backend.api.config import ROOT,Settings


def main():
    transcript={'fixture_notice':'Isolated local API demonstration, not real-user feedback or ML training interactions.',
                'steps':[],'test_split_accessed':False}
    password=secrets.token_urlsafe(32)
    with tempfile.TemporaryDirectory(prefix='humsafar_api_demo_') as directory:
        settings=Settings('sqlite:///'+(Path(directory)/'workflow.db').as_posix(),secrets.token_urlsafe(48))
        app=create_app(settings)
        with TestClient(app) as client:
            def call(method,path,label,expected,**kwargs):
                result=client.request(method,path,**kwargs)
                if result.status_code!=expected:raise RuntimeError(f'{label} failed ({result.status_code}): {result.text}')
                transcript['steps'].append({'action':label,'method':method,'path':path,'status':result.status_code})
                return result.json() if result.content else None
            headers={}
            for member in ['demo-owner','demo-member']:
                call('POST','/auth/register','Register '+member,201,
                    json={'email':member+'@example.com','display_name':member,'password':password})
                token=call('POST','/auth/login','Login '+member,200,
                    data={'username':member+'@example.com','password':password})
                headers[member]={'Authorization':'Bearer '+token['access_token']}
            owner,member=headers['demo-owner'],headers['demo-member']
            created=call('POST','/groups','Create group',201,headers=owner,json={'name':'HumSafar isolated workflow demo'})
            gid=created['group']['id']
            call('POST','/groups/join','Join group',200,headers=member,json={'invitation_code':created['invitation_code']})
            for who,interests in [('demo-owner',['mountains','hiking','nature']),('demo-member',['lakes','beautiful scenery'])]:
                call('PUT',f'/groups/{gid}/preferences/me','Save own preferences: '+who,200,headers=headers[who],
                     json={'interests':interests,'preferred_countries':['Pakistan'],
                           'budget_min':'100','budget_max':'500','currency':'USD',
                           'start_date':'2030-06-01','end_date':'2030-06-10'})
            rec=call('POST',f'/groups/{gid}/recommendations','Generate consensus recommendations',201,
                headers=owner,json={'scope':'pakistan','country':'Pakistan','method':'adaptive_consensus','top_k':5})
            selected=rec['payload']['results'][0]
            for who in ['demo-owner','demo-member']:
                call('PUT',f'/groups/{gid}/recommendations/{rec["id"]}/vote','Vote: '+who,200,
                     headers=headers[who],json={'destination_id':selected['destination_id']})
            totals=call('GET',f'/groups/{gid}/recommendations/{rec["id"]}/votes','Read vote totals',200,headers=member)
            planned=call('POST',f'/groups/{gid}/itinerary','Create persisted itinerary item',201,headers=owner,
                json={'recommendation_id':rec['id'],'destination_id':selected['destination_id'],
                      'position':1,'planned_date':'2030-06-02','notes':'Example plan; no booking or availability claim'})
            call('GET',f'/groups/{gid}/itinerary','Read persisted itinerary as member',200,headers=member)
            transcript.update(selected_destination=selected,member_modes=rec['payload']['member_modes'],
                unsupported_filter_notices=rec['warnings'],votes_for_selection=next(r['votes'] for r in totals if r['destination_id']==selected['destination_id']),
                itinerary_position=planned['position'],workflow_complete=True)
        # The SQLite file persists across separate app/engine instances.
        with TestClient(create_app(settings)) as restarted:
            response=restarted.get(f'/groups/{gid}/itinerary',headers=owner)
            if response.status_code!=200 or response.json()[0]['id']!=planned['id']:
                raise RuntimeError('Restart persistence verification failed')
            transcript['persistence_after_restart_verified']=True
    output=ROOT/'backend/var/api_workflow_demo.json'
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(transcript,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'workflow_complete':True,'requests':len(transcript['steps']),
        'selected_destination':selected['name'],'votes':transcript['votes_for_selection'],
        'persistence_after_restart_verified':True,'transcript':str(output)},indent=2))


if __name__=='__main__':main()
