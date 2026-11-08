"""Example API-free requests, not real user preferences or generated ratings."""
import json

from backend.catalog import CATALOG_DIR
from backend.recommendation_service import RecommendationService,UserContext,GroupMember


def main():
    service=RecommendationService()
    known=UserContext('google_local_hawaii',service._bpr().users[0])
    results={
        'known_hawaii_user':service.recommend(scope='hawaii',user=known),
        'new_hawaii_user':service.recommend(scope='hawaii',preferences='beach hiking'),
        'new_user_without_preferences':service.recommend(scope='hawaii'),
        'pakistan_content':service.recommend(scope='pakistan',preferences='mountains hiking nature'),
        'italy_hotel_metadata':service.recommend(country='Italy',kind='hotel',preferences='historic hotel'),
        'italy_attraction_gap':service.recommend(country='Italy',kind='attraction',preferences='history'),
        'preference_group':service.recommend_group([
            GroupMember('example_request_a','mountains hiking nature'),
            GroupMember('example_request_b','lakes beautiful scenery')],scope='pakistan'),
    }
    (CATALOG_DIR/'service_demo.json').write_text(json.dumps(results,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps({key:{'status':value['status'],'mode':value.get('mode'),'results':len(value['results'])} for key,value in results.items()},indent=2))


if __name__=='__main__':main()
