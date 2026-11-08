"""Explain shared constraints using only saved application preferences/catalog."""
from collections import Counter

from backend.catalog import country_mapping
from backend.api.schemas import Preferences


def availability(member_ids,preferences):
    dated=[(u,p) for u,p in preferences.items() if p.start_date]
    missing=[u for u in member_ids if u not in preferences or not preferences[u].start_date]
    start=max((p.start_date for _,p in dated),default=None)
    end=min((p.end_date for _,p in dated),default=None)
    state='unknown' if not dated else 'conflict' if start>end else 'incomplete' if missing else 'overlap'
    messages={
        'unknown':'No travel dates saved yet. Each member can add their own availability.',
        'conflict':'The saved travel windows do not overlap. Members must update their own dates; no shared date can be assigned yet.',
        'incomplete':'These dates overlap for members who supplied availability. Other members still need to confirm their dates.',
        'overlap':'All members have a shared travel window. These are calendar dates, not venue availability.'}
    return {'status':state,'start_date':start if state!='conflict' else None,
            'end_date':end if state!='conflict' else None,'members_with_dates':len(dated),
            'members_total':len(member_ids),'missing_user_ids':missing,'message':messages[state]}


def mandatory_filter(records,preferences):
    for pref in preferences:
        if pref.preferred_countries and pref.country_requirement=='mandatory':
            allowed={country_mapping(c).casefold() for c in pref.preferred_countries if country_mapping(c)}
            records=[r for r in records if r.country and r.country.casefold() in allowed]
        if pref.preferred_regions:
            records=[r for r in records if r.city_or_region and r.city_or_region.casefold() in {x.casefold() for x in pref.preferred_regions}]
        if pref.preferred_destination_ids and pref.destination_requirement=='mandatory':
            records=[r for r in records if r.destination_id in pref.preferred_destination_ids]
    return records


def summary(base,members,preference_rows,scope='catalog',kind='attraction'):
    preferences={row.user_id:Preferences.model_validate(row.values) for row in preference_rows}
    public=[]
    for user in members:
        pref=preferences.get(user.id,Preferences())
        public.append({'user_id':user.id,'display_name':user.display_name,'has_preferences':user.id in preferences,
            **pref.model_dump(include={'preferred_countries','country_requirement','preferred_destination_ids','destination_requirement','preferred_regions','start_date','end_date'})})
    records=base.candidates(scope=scope,kind=kind)
    compatible=mandatory_filter(records,list(preferences.values()))
    countries=dict(sorted(Counter(r.country for r in compatible if r.country).items()))
    chosen={country_mapping(c) for pref in preferences.values() for c in pref.preferred_countries}
    all_countries={r.country for r in records if r.country}
    unavailable=sorted(c for c in chosen if c and c not in all_countries)
    mandatory=[{country_mapping(c) for c in p.preferred_countries} for p in preferences.values()
               if p.preferred_countries and p.country_requirement=='mandatory']
    conflict=bool(mandatory) and not set.intersection(*mandatory)
    if not compatible and (conflict or any(p.preferred_regions or (p.preferred_destination_ids and p.destination_requirement=='mandatory') for p in preferences.values())):
        state='mandatory_conflict'
    elif not compatible:state='no_catalog_coverage'
    elif len({tuple(sorted(p.preferred_countries)) for p in preferences.values() if p.preferred_countries})>1:state='different_preferences'
    else:state='compatible'
    messages=[]
    if state=='mandatory_conflict':messages.append('Mandatory restrictions leave no common catalog options. Only each member can change their own restrictions; the system will not override them.')
    if state=='different_preferences':messages.append('Members prefer different countries. Flexible preferences can be balanced; mandatory restrictions remain enforced.')
    if state=='no_catalog_coverage':messages.append('No records in this scope satisfy the mandatory choices. Try a genuinely covered scope or ask members to review their own restrictions.')
    if unavailable:messages.append('Some requested countries have no '+kind+' records in this scope. Hotel metadata is not attraction coverage.')
    if countries:messages.append('Compatible options below satisfy every saved mandatory restriction; they are alternatives, not an agreed destination.')
    return {'members':public,'availability':availability([u.id for u in members],preferences),
            'country_status':state,'messages':messages,'compatible_countries':countries,
            'unavailable_preferred_countries':unavailable,'candidate_count':len(compatible),'scope':scope,'kind':kind}
