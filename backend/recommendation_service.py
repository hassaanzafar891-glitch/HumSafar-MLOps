"""Reusable local service with explicit geography/model/identity boundaries."""
from dataclasses import dataclass, replace
import re

import numpy as np
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS
from sklearn.metrics.pairwise import cosine_similarity

from backend.catalog import load_catalog
from backend.group_consensus import ConsensusConfig, aggregate, satisfaction


@dataclass(frozen=True)
class UserContext:
    namespace: str
    user_id: str


@dataclass(frozen=True)
class GroupMember:
    member_id: str
    preferences: str | None = None
    user: UserContext | None = None


def tokens(text):
    return set(re.findall(r'(?u)\b\w\w+\b',text.lower()))-ENGLISH_STOP_WORDS


def preference_scores(preferences, records):
    """Exact metadata query-token coverage; no new model fitting or ratings."""
    query=tokens(preferences)
    if not query:
        return np.zeros(len(records))
    values=[]
    for row in records:
        available=' '.join([row.name,*row.categories,row.description or '',row.country or '',row.city_or_region or '',row.address or ''])
        values.append(len(query & tokens(available))/len(query))
    return np.asarray(values,dtype=float)


def aggregate_preference_scores(candidate_ids, member_scores, method='adaptive_consensus', config=ConsensusConfig()):
    """Reusable AGC for complete explicit caller-supplied [0,1] utilities.

    Missing utilities are rejected rather than imputed as dislikes. These values
    are caller-supplied or predicted utilities, not newly observed rating data.
    """
    ids=sorted(candidate_ids)
    if not ids or len(ids)!=len(set(ids)) or len(member_scores)<2:
        raise ValueError('Unique nonempty candidates and at least two members required')
    members=sorted(member_scores)
    for member in members:
        if set(member_scores[member])!=set(ids):
            raise ValueError('Each member must explicitly score every candidate; no missing-score imputation')
    matrix=np.array([[member_scores[u][item] for item in ids] for u in members],dtype=float)
    selected=aggregate(matrix,method,replace(config,top_k=min(config.top_k,len(ids))))
    utilities=matrix[:,selected].mean(axis=1)
    return {'destination_ids':[ids[i] for i in selected],
            'member_utilities':dict(zip(members,utilities.tolist())),
            'utility_summary':satisfaction(utilities),'method':method,
            'utility_interpretation':'Caller-supplied or predicted utility, not verified ground-truth group satisfaction.'}


class RecommendationService:
    def __init__(self, catalog=None):
        self.catalog=load_catalog() if catalog is None else [r.validate() for r in catalog]
        if len({r.destination_id for r in self.catalog})!=len(self.catalog):
            raise ValueError('Duplicate catalog identities')
        self.by_id={r.destination_id:r for r in self.catalog}
        self._bpr_model=None
        self._tfidf_model=None

    def _bpr(self):
        if self._bpr_model is None:
            from backend.train_bpr import BPR
            self._bpr_model=BPR.load()
        return self._bpr_model

    def _tfidf(self):
        if self._tfidf_model is None:
            from backend.recommender import DestinationRecommender
            self._tfidf_model=DestinationRecommender.load()
        return self._tfidf_model

    def candidates(self,scope='catalog',country=None,kind='attraction'):
        if scope not in ['catalog','hawaii','pakistan'] or kind not in ['attraction','hotel']:
            raise ValueError('Unknown scope or catalog kind')
        source={'hawaii':'google_local_hawaii','pakistan':'pakistan_tourism'}.get(scope)
        return sorted([r for r in self.catalog if r.kind==kind and
                       (source is None or r.data_source==source) and
                       (country is None or r.country==country)],key=lambda r:r.destination_id)

    def _scores(self,records,scope,preferences,user):
        # Never transfer user factors merely because a country, name, or numeric
        # user ID happens to match. Both identity namespace and source IDs matter.
        known_hawaii_history=set()
        if scope=='hawaii' and user is not None and user.namespace=='google_local_hawaii':
            model=self._bpr()
            known_hawaii_history=model.histories.get(user.user_id,set())
            if (user.user_id in model.user_lookup
                and np.any(model.user_factors[model.user_lookup[user.user_id]]!=0)
                and all(
                r.kind=='attraction' and r.data_source=='google_local_hawaii'
                and r.country=='United States' and 'hawaii_bpr' in r.model_compatibility
                and r.source_id in model.item_lookup for r in records)):
                bpr,pop,allowed=model.normalized_components([user.user_id])
                indices=[model.item_lookup[r.source_id] for r in records]
                values=(.75*bpr[0]+.25*pop[0])[indices]
                values[~allowed[0,indices]]=-np.inf
                return values,'hawaii_personalized_hybrid',True
        if not isinstance(preferences,str) or not preferences.strip():
            return None,'needs_preferences',False
        if scope=='pakistan' and all(r.data_source=='pakistan_tourism' and r.country=='Pakistan'
                                    and 'pakistan_tfidf' in r.model_compatibility for r in records):
            model=self._tfidf()
            lookup={r['destination']:i for i,r in enumerate(model.destinations)}
            if all(r.source_id in lookup for r in records):
                query=model.vectorizer.transform([preferences])
                values=cosine_similarity(query,model.matrix).ravel()
                return values[[lookup[r.source_id] for r in records]],'pakistan_tfidf_content',False
        values=preference_scores(preferences,records)
        for index,row in enumerate(records):
            if row.data_source=='google_local_hawaii' and row.source_id in known_hawaii_history:
                values[index]=-np.inf
        return values,'metadata_preference',False

    @staticmethod
    def _result(row,score):
        return {'destination_id':row.destination_id,'name':row.name,'kind':row.kind,
                'country':row.country,'city_or_region':row.city_or_region,
                'categories':row.categories,'data_source':row.data_source,'score':float(score)}

    def recommend(self,preferences=None,user=None,scope='catalog',country=None,kind='attraction',top_k=5):
        if isinstance(top_k,bool) or not isinstance(top_k,int) or top_k<1:
            raise ValueError('top_k must be a positive integer')
        records=self.candidates(scope,country,kind)
        base={'scope':scope,'country_filter':country,'kind':kind,
              'score_interpretation':'Mode-specific ranking utility, not a probability; do not compare scores across modes.'}
        if not records:
            return dict(base,status='no_candidates',mode=None,personalized=False,results=[])
        scores,mode,personalized=self._scores(records,scope,preferences,user)
        if scores is None:
            return dict(base,status='needs_preferences',mode=mode,personalized=False,results=[],
                        next_step='Provide travel interests/preferences and a geographic scope. No user embedding or ratings will be created.')
        order=sorted(range(len(records)),key=lambda i:(-scores[i],records[i].destination_id))
        selected=[i for i in order if np.isfinite(scores[i]) and (personalized or scores[i]>0)][:top_k]
        return dict(base,status='ok' if selected else 'no_matching_preferences',mode=mode,personalized=personalized,
                    results=[self._result(records[i],scores[i]) for i in selected])

    def group_from_scores(self,member_scores,method='adaptive_consensus',config=ConsensusConfig()):
        if not member_scores:
            raise ValueError('No members supplied')
        candidates=list(next(iter(member_scores.values())))
        if any(item not in self.by_id for item in candidates):
            raise ValueError('Unknown unified catalog destination ID')
        return aggregate_preference_scores(candidates,member_scores,method,config)

    def recommend_group(self,members,scope='catalog',country=None,kind='attraction',method='adaptive_consensus',config=ConsensusConfig()):
        if len(members)<2 or len({m.member_id for m in members})!=len(members):
            raise ValueError('At least two distinct group members required')
        records=self.candidates(scope,country,kind)
        if not records:
            return {'status':'no_candidates','results':[]}
        member_values,modes={},{}
        for member in members:
            values,mode,_=self._scores(records,scope,member.preferences,member.user)
            if values is None:
                return {'status':'needs_preferences','member_id':member.member_id,'results':[]}
            member_values[member.member_id]=values
            modes[member.member_id]=mode
        matrix=np.array(list(member_values.values()))
        common=np.isfinite(matrix).all(axis=0)
        # Zero lexical score means no matching metadata evidence, not dislike.
        # Do not pad the group list with candidates that score zero for everyone.
        common &= np.where(np.isfinite(matrix),matrix,0).max(axis=0)>0
        if not common.any() or any(not np.any(values[common]>0) for values in member_values.values()):
            return {'status':'insufficient_preference_signal','results':[],
                    'next_step':'Ask each member for clearer interests; do not invent missing preferences.'}
        explicit={member:{row.destination_id:float(values[i]) for i,row in enumerate(records) if common[i]}
                  for member,values in member_values.items()}
        group=self.group_from_scores(explicit,method,config)
        return dict(group,status='ok',member_modes=modes,
                    results=[self._result(self.by_id[item],float(np.mean([v[item] for v in explicit.values()]))) for item in group['destination_ids']],
                    score_interpretation='Results score is mean member utility, not the sequential AGC objective or a probability. Utilities from different modes are not calibrated welfare measures.')
