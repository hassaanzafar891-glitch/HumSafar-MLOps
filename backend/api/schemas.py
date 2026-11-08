from datetime import date,datetime
from decimal import Decimal
from typing import Annotated,Literal

from pydantic import BaseModel,ConfigDict,EmailStr,Field,SecretStr,model_validator

Short=Annotated[str,Field(min_length=1,max_length=80)]
Identifier=Annotated[str,Field(min_length=1,max_length=160)]


class Input(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)


class Output(BaseModel):
    model_config=ConfigDict(from_attributes=True)


class Register(Input):
    email:EmailStr
    display_name:Short
    password:SecretStr=Field(min_length=12,max_length=128)


class ProfilePatch(Input):
    display_name:Short
    bio:str=Field(default='',max_length=500)


class PasswordChange(Input):
    current_password:SecretStr=Field(max_length=128)
    new_password:SecretStr=Field(min_length=12,max_length=128)


class UserOut(Output):
    id:str
    email:EmailStr
    display_name:str
    bio:str
    created_at:datetime


class TokenOut(BaseModel):
    access_token:str
    token_type:Literal['bearer']='bearer'
    expires_in:int


class HealthOut(BaseModel):
    status:Literal['ok']
    schema_version:int


class CatalogEntry(BaseModel):
    destination_id:str
    name:str
    country:str | None
    city_or_region:str | None
    kind:Literal['attraction','hotel']
    categories:list[str]
    latitude:float | None
    longitude:float | None
    model_compatibility:list[str]


class CatalogPage(BaseModel):
    total:int
    items:list[CatalogEntry]


class CoverageOut(BaseModel):
    model_config=ConfigDict(extra='allow')
    total_source_listings:int
    named_country_or_territory_labels:int
    country_counts:dict[str,int]
    country_counts_by_kind:dict[str,dict[str,int]]
    unknown_country_listings:int


class GroupCreate(Input):
    name:str=Field(min_length=1,max_length=100)


class GroupPatch(Input):
    name:str | None=Field(default=None,min_length=1,max_length=100)
    archived:bool | None=None


class Join(Input):
    invitation_code:str=Field(min_length=20,max_length=200)


class Transfer(Input):
    user_id:str=Field(min_length=36,max_length=36)


class GroupOut(Output):
    id:str
    name:str
    owner_id:str
    revision:int
    archived:bool
    created_at:datetime


class GroupCreated(BaseModel):
    group:GroupOut
    invitation_code:str


class InvitationOut(BaseModel):
    invitation_code:str


class MemberOut(BaseModel):
    user_id:str
    display_name:str
    role:str
    joined_at:datetime


class Preferences(Input):
    interests:list[Short]=Field(default_factory=list,max_length=30)
    free_text:str=Field(default='',max_length=1000)
    budget_min:Decimal | None=Field(default=None,ge=0,le=1000000000,allow_inf_nan=False)
    budget_max:Decimal | None=Field(default=None,ge=0,le=1000000000,allow_inf_nan=False)
    currency:str | None=Field(default=None,pattern=r'^[A-Z]{3}$')
    preferred_countries:list[Short]=Field(default_factory=list,max_length=20)
    country_requirement:Literal['preferred','mandatory']='mandatory'
    preferred_destination_ids:list[Identifier]=Field(default_factory=list,max_length=100)
    destination_requirement:Literal['preferred','mandatory']='mandatory'
    preferred_regions:list[Short]=Field(default_factory=list,max_length=20)
    start_date:date | None=None
    end_date:date | None=None

    @model_validator(mode='after')
    def ranges(self):
        if self.budget_min is not None and self.budget_max is not None and self.budget_min>self.budget_max:
            raise ValueError('budget_min must not exceed budget_max')
        if (self.budget_min is not None or self.budget_max is not None) and self.currency is None:
            raise ValueError('currency required when a budget is supplied')
        if (self.start_date is None)!=(self.end_date is None):
            raise ValueError('Provide both start_date and end_date')
        if self.start_date and self.end_date<self.start_date:
            raise ValueError('end_date must not precede start_date')
        for values in [self.interests,self.preferred_countries,self.preferred_destination_ids,self.preferred_regions]:
            if len(values)!=len(set(values)):
                raise ValueError('Preference lists must not contain duplicates')
        return self


class PreferenceOut(BaseModel):
    group_id:str
    user_id:str
    values:Preferences
    updated_at:datetime


class RecommendationRequest(Input):
    scope:Literal['catalog','hawaii','pakistan']='catalog'
    kind:Literal['attraction','hotel']='attraction'
    country:Short | None=None
    method:Literal['average','least_misery','adaptive_consensus']='adaptive_consensus'
    top_k:int=Field(default=10,ge=1,le=20,strict=True)


class DestinationResult(BaseModel):
    destination_id:str
    name:str
    kind:Literal['attraction','hotel']
    country:str | None
    city_or_region:str | None
    categories:list[str]
    data_source:str
    score:float


class RecommendationPayload(BaseModel):
    model_config=ConfigDict(extra='allow')
    status:str
    results:list[DestinationResult]
    mode:str | None=None
    personalized:bool=False
    member_modes:dict[str,str]=Field(default_factory=dict)
    utility_summary:dict[str,float] | None=None


class FilterNotice(BaseModel):
    code:str
    message:str


class RecommendationOut(BaseModel):
    id:str
    group_id:str
    created_by:str
    group_revision:int
    is_current:bool
    method:str
    filters:dict
    warnings:list[FilterNotice]
    payload:RecommendationPayload
    created_at:datetime


class VoteRequest(Input):
    destination_id:Identifier


class VoteOut(Output):
    id:str
    group_id:str
    recommendation_id:str
    user_id:str
    destination_id:str
    updated_at:datetime


class VoteCount(BaseModel):
    destination_id:str
    votes:int


class ItineraryCreate(Input):
    recommendation_id:str=Field(min_length=36,max_length=36)
    destination_id:Identifier
    position:int=Field(ge=1,le=1000,strict=True)
    planned_date:date | None=None
    notes:str=Field(default='',max_length=1000)


class ItineraryPatch(Input):
    position:int=Field(ge=1,le=1000,strict=True)
    planned_date:date | None=None
    notes:str=Field(default='',max_length=1000)


class ItineraryOut(Output):
    id:str
    group_id:str
    recommendation_id:str
    destination_id:str
    destination_snapshot:dict
    position:int
    planned_date:date | None
    notes:str
    created_by:str


class SharedAvailability(BaseModel):
    status:Literal['unknown','incomplete','overlap','conflict']
    start_date:date | None=None
    end_date:date | None=None
    members_with_dates:int
    members_total:int
    missing_user_ids:list[str]
    message:str


class PlanningMember(BaseModel):
    user_id:str
    display_name:str
    has_preferences:bool
    preferred_countries:list[str]
    country_requirement:Literal['preferred','mandatory']
    preferred_destination_ids:list[str]
    destination_requirement:Literal['preferred','mandatory']
    preferred_regions:list[str]
    start_date:date | None
    end_date:date | None


class PlanningOut(BaseModel):
    members:list[PlanningMember]
    availability:SharedAvailability
    country_status:Literal['compatible','different_preferences','mandatory_conflict','no_catalog_coverage']
    messages:list[str]
    compatible_countries:dict[str,int]
    unavailable_preferred_countries:list[str]
    candidate_count:int
    scope:str
    kind:str


class VotingMember(BaseModel):
    user_id:str
    display_name:str
    destination_id:str | None


class VotingSummary(BaseModel):
    recommendation_id:str
    eligible_to_vote:bool
    total_members:int
    total_votes:int
    own_destination_id:str | None
    choices:list[VoteCount]
    members:list[VotingMember]
