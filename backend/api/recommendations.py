"""Enforce saved application preferences before calling the existing service."""
from datetime import date

from fastapi import HTTPException

from backend.catalog import country_mapping
from backend.group_consensus import ConsensusConfig
from backend.recommendation_service import RecommendationService,GroupMember
from backend.api.schemas import Preferences
from backend.api.planning import mandatory_filter
from backend.recommendation_service import UserContext
import numpy as np


class PlanningService(RecommendationService):
    def __init__(self,records,preferences):
        super().__init__(records)
        self.preferences=preferences

    def _scores(self,records,scope,preferences,user):
        values,mode,personalized=super()._scores(records,scope,preferences,user)
        if values is None or user is None:return values,mode,personalized
        pref=self.preferences.get(user.user_id)
        if pref is None:return values,mode,personalized
        components=[]
        if pref.country_requirement=='preferred' and pref.preferred_countries:
            wanted={country_mapping(c).casefold() for c in pref.preferred_countries if country_mapping(c)}
            components.append(np.array([float(bool(r.country and r.country.casefold() in wanted)) for r in records]))
        if pref.destination_requirement=='preferred' and pref.preferred_destination_ids:
            components.append(np.array([float(r.destination_id in pref.preferred_destination_ids) for r in records]))
        if components:
            finite=np.isfinite(values)
            values=values.copy()
            values[finite]=.85*values[finite]+.15*np.mean(components,axis=0)[finite]
        return values,mode,personalized


def filtered_service(base,preference_rows,request):
    preferences=[Preferences.model_validate(row.values) for row in preference_rows]
    records=base.candidates(request.scope,request.country,request.kind)
    records=mandatory_filter(records,preferences)
    if not records:
        raise HTTPException(409,detail={'code':'no_compatible_candidates',
            'message':'No catalog items satisfy the requested scope and all saved geographic/destination constraints. Missing geography is not inferred.'})
    selected=PlanningService(records,{row.user_id:pref for row,pref in zip(preference_rows,preferences)})
    selected._bpr_model=base._bpr_model
    selected._tfidf_model=base._tfidf_model
    notices=[{'code':'new_application_users','message':'Application users are not historical Hawaii identities. Recommendations use supplied-preference content matching; no user embeddings or ratings are created.'}]
    if any((p.preferred_countries and p.country_requirement=='preferred') or (p.preferred_destination_ids and p.destination_requirement=='preferred') for p in preferences):
        notices.append({'code':'flexible_preferences','message':'Flexible country/destination choices influence scores (85% interest matching, 15% stated geographic preference) but do not exclude alternatives. Mandatory restrictions are never relaxed.'})
    if any(p.budget_min is not None or p.budget_max is not None for p in preferences):
        notices.append({'code':'budget_filter_unsupported','message':'Budget/currency saved only: the catalog has no reliable comparable trip prices or currency conversion. No budget filtering was applied.'})
    dated=[p for p in preferences if p.start_date]
    if dated:
        notices.append({'code':'date_availability_unsupported','message':'Travel dates saved only: catalog opening schedules, capacity and live availability are unavailable. No attraction availability filtering was applied.'})
        if max(p.start_date for p in dated)>min(p.end_date for p in dated):
            notices.append({'code':'member_date_conflict','message':'Member travel-date windows do not overlap. Resolve dates before assigning itinerary dates.'})
    filters={'requested':request.model_dump(mode='json'),
             'applied':['scope','kind','requested_country','intersection_of_mandatory_countries_regions_and_destination_ids'],
             'interests':'Soft text/category preference scoring, not a guaranteed category match.',
             'remaining_candidates':len(records)}
    return selected,notices,filters


def generate(base,preference_rows,request,individual=False):
    selected,notices,filters=filtered_service(base,preference_rows,request)
    members=[]
    for row in preference_rows:
        pref=Preferences.model_validate(row.values)
        text=' '.join([*pref.interests,pref.free_text]).strip()
        if not text:
            raise HTTPException(409,detail={'code':'preferences_required','message':'Each member must supply interests or free-text preferences.','user_id':row.user_id})
        # No endpoint accepts a historical Google user_id/namespace. App UUIDs
        # and sample dataset IDs are never linked automatically.
        members.append(GroupMember(row.user_id,preferences=text,user=UserContext('humsafar',row.user_id)))
    if individual:
        payload=selected.recommend(scope=request.scope,country=request.country,kind=request.kind,
                                   preferences=members[0].preferences,user=members[0].user,top_k=request.top_k)
    else:
        payload=selected.recommend_group(members,scope=request.scope,country=request.country,kind=request.kind,
            method=request.method,config=ConsensusConfig(top_k=request.top_k))
    if payload['status']!='ok':
        raise HTTPException(409,detail={'code':payload['status'],'message':payload.get('next_step','Saved preferences have insufficient metadata matches; revise preferences or scope.')})
    return payload,notices,filters


def check_itinerary_date(planned_date,preference_rows):
    if planned_date:
        for row in preference_rows:
            pref=Preferences.model_validate(row.values)
            if pref.start_date and not pref.start_date<=planned_date<=pref.end_date:
                raise HTTPException(409,'Itinerary date falls outside a member travel window. Venue availability has not been checked.')
