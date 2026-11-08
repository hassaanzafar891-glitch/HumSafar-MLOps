from contextlib import asynccontextmanager
import threading
import time

import jwt
from fastapi import Depends,FastAPI,HTTPException,Request,Response,status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordBearer,OAuth2PasswordRequestForm
from sqlalchemy import delete,func,select,update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.api.config import Settings
from backend.api.database import database,initialize_schema,verify_schema
from backend.api.models import User,TravelGroup,Membership,MemberPreference,GroupRecommendation,Vote,ItineraryItem
from backend.api.recommendations import generate,check_itinerary_date
from backend.api.planning import summary as planning_summary
from backend.api import schemas as s
from backend.api.security import PASSWORDS,DUMMY_HASH,access_token,decode_token,invitation,invite_digest,verify_password
from backend.catalog import coverage
from backend.recommendation_service import RecommendationService


def create_app(settings=None,service=None):
    settings=(settings or Settings.from_env()).validate()
    engine,sessions=database(settings.database_url)

    @asynccontextmanager
    async def lifespan(app):
        if settings.auto_init_db:initialize_schema(engine)
        else:verify_schema(engine)
        app.state.service=service if service is not None else RecommendationService()
        app.state.coverage=coverage(app.state.service.catalog)
        try:yield
        finally:engine.dispose()

    app=FastAPI(title='HumSafar API',version='0.1.0',lifespan=lifespan,
        description='International group travel planning. Application users use preference-based recommendations; historical Hawaii identities are never assigned automatically. Budget/live availability filtering is unsupported and explicitly reported.')
    app.state.engine,app.state.sessions=engine,sessions
    oauth=OAuth2PasswordBearer(tokenUrl='/auth/login')
    buckets={}
    bucket_lock=threading.Lock()

    @app.middleware('http')
    async def response_headers(request,call_next):
        response=await call_next(request)
        response.headers['X-Content-Type-Options']='nosniff'
        if request.url.path.startswith(('/auth','/users','/groups')):
            response.headers['Cache-Control']='no-store'
        return response

    def limited(request,action,limit=20,window=60):
        key=(action,request.client.host if request.client else 'unknown')
        tick=time.monotonic()
        with bucket_lock:
            if len(buckets)>5000:
                for old in list(buckets):
                    if buckets[old][1]<=tick:del buckets[old]
                if len(buckets)>5000:
                    raise HTTPException(429,'Local request limiter capacity reached',headers={'Retry-After':'60'})
            count,expiry=buckets.get(key,(0,tick+window))
            if tick>=expiry:count,expiry=0,tick+window
            if count>=limit:
                raise HTTPException(429,'Too many attempts; try again later',headers={'Retry-After':str(max(1,int(expiry-tick)))})
            buckets[key]=(count+1,expiry)

    def get_db():
        with sessions() as session:
            try:yield session
            finally:
                if session.in_transaction():session.rollback()

    def unauthorized():return HTTPException(401,'Invalid or expired credentials',headers={'WWW-Authenticate':'Bearer'})

    def current_user(token:str=Depends(oauth),db:Session=Depends(get_db)):
        try:
            if len(token)>8192:raise ValueError('Oversized token')
            payload=decode_token(token,settings)
            user=db.get(User,payload['sub'])
            if user is None or payload['ver']!=user.token_version:raise ValueError('Invalid user/token version')
        except (jwt.InvalidTokenError,ValueError,TypeError,KeyError):raise unauthorized()
        return user

    def member_group(db,group_id,user):
        group=db.get(TravelGroup,group_id)
        membership=db.get(Membership,(group_id,user.id))
        if group is None or membership is None:raise HTTPException(404,'Group not found')
        return group

    def owner_group(db,group_id,user):
        group=member_group(db,group_id,user)
        if group.owner_id!=user.id:raise HTTPException(403,'Group owner permission required')
        return group

    def active(group):
        if group.archived:raise HTTPException(409,'Group is archived')

    def bump(db,group):
        db.execute(update(TravelGroup).where(TravelGroup.id==group.id).values(revision=TravelGroup.revision+1))

    def recommendation(db,group,rec_id,require_current=False):
        row=db.get(GroupRecommendation,rec_id)
        if row is None or row.group_id!=group.id:raise HTTPException(404,'Recommendation not found')
        if require_current and row.group_revision!=group.revision:
            raise HTTPException(409,'Recommendation is stale after membership/preferences changes; regenerate before voting or itinerary selection')
        return row

    def recommendation_out(row,group):
        return s.RecommendationOut(id=row.id,group_id=row.group_id,created_by=row.created_by,
            group_revision=row.group_revision,is_current=row.group_revision==group.revision,
            method=row.method,filters=row.filters,warnings=row.warnings,payload=row.payload,created_at=row.created_at)

    def selected_destination(row,destination_id):
        for item in row.payload['results']:
            if item['destination_id']==destination_id:return item
        raise HTTPException(422,'Destination is not among this saved recommendation list')

    def require_group_recommendation(row):
        if row.method=='individual':
            raise HTTPException(409,'Generate an all-member group recommendation before group voting or itinerary selection')

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_,exc):
        # Do not echo password/token/preference input values in validation errors.
        return JSONResponse(status_code=422,content={'detail':[{'loc':list(e['loc']),'msg':e['msg'],'type':e['type']} for e in exc.errors()]})

    @app.exception_handler(IntegrityError)
    async def conflict(_request,_exc):
        return JSONResponse(status_code=409,content={'detail':'Conflicting or invalid database record; reload and retry'})

    @app.get('/health',response_model=s.HealthOut,tags=['system'])
    def health():return {'status':'ok','schema_version':1}

    @app.post('/auth/register',response_model=s.UserOut,status_code=201,tags=['auth'])
    def register(body:s.Register,request:Request,db:Session=Depends(get_db)):
        limited(request,'register',10,300)
        email=str(body.email).casefold()
        if db.scalar(select(User.id).where(User.email==email)):
            raise HTTPException(409,'Email already registered')
        user=User(email=email,display_name=body.display_name,password_hash=PASSWORDS.hash(body.password.get_secret_value()))
        db.add(user);db.commit()
        return user

    @app.post('/auth/login',response_model=s.TokenOut,tags=['auth'])
    def login(request:Request,response:Response,form:OAuth2PasswordRequestForm=Depends(),db:Session=Depends(get_db)):
        limited(request,'login')
        user=db.scalar(select(User).where(User.email==form.username.strip().casefold()))
        valid=verify_password(form.password,user.password_hash if user else DUMMY_HASH)
        if not valid or user is None:raise unauthorized()
        response.headers['Cache-Control']='no-store'
        return s.TokenOut(access_token=access_token(user,settings),expires_in=settings.access_token_minutes*60)

    @app.post('/auth/logout',status_code=204,tags=['auth'])
    def logout(user:User=Depends(current_user),db:Session=Depends(get_db)):
        db.execute(update(User).where(User.id==user.id).values(token_version=User.token_version+1));db.commit()
        return Response(status_code=204)

    @app.get('/users/me',response_model=s.UserOut,tags=['users'])
    def profile(user:User=Depends(current_user)):return user

    @app.patch('/users/me',response_model=s.UserOut,tags=['users'])
    def update_profile(body:s.ProfilePatch,user:User=Depends(current_user),db:Session=Depends(get_db)):
        user.display_name,user.bio=body.display_name,body.bio;db.commit();return user

    @app.post('/users/me/password',status_code=204,tags=['users'])
    def change_password(body:s.PasswordChange,user:User=Depends(current_user),db:Session=Depends(get_db)):
        if not verify_password(body.current_password.get_secret_value(),user.password_hash):raise unauthorized()
        user.password_hash=PASSWORDS.hash(body.new_password.get_secret_value())
        db.execute(update(User).where(User.id==user.id).values(token_version=User.token_version+1));db.commit()
        return Response(status_code=204)

    @app.get('/catalog/coverage',response_model=s.CoverageOut,tags=['catalog'])
    def catalog_coverage(request:Request)->dict:return request.app.state.coverage

    @app.get('/catalog',response_model=s.CatalogPage,tags=['catalog'])
    def catalog(request:Request,country:str | None=None,kind:str='attraction',limit:int=20,offset:int=0)->dict:
        if kind not in ['attraction','hotel'] or not 1<=limit<=100 or offset<0:raise HTTPException(422,'Invalid catalog pagination or kind')
        items=request.app.state.service.candidates(country=country,kind=kind)
        return {'total':len(items),'items':[dict(destination_id=r.destination_id,name=r.name,country=r.country,
            city_or_region=r.city_or_region,kind=r.kind,categories=r.categories,latitude=r.latitude,longitude=r.longitude,
            model_compatibility=r.model_compatibility) for r in items[offset:offset+limit]]}

    @app.post('/groups',response_model=s.GroupCreated,status_code=201,tags=['groups'])
    def create_group(body:s.GroupCreate,user:User=Depends(current_user),db:Session=Depends(get_db)):
        code,digest=invitation()
        group=TravelGroup(name=body.name,owner_id=user.id,invite_digest=digest)
        db.add(group);db.flush()
        db.add(Membership(group_id=group.id,user_id=user.id,role='owner'));db.commit()
        return s.GroupCreated(group=s.GroupOut.model_validate(group),invitation_code=code)

    @app.get('/groups',response_model=list[s.GroupOut],tags=['groups'])
    def groups(user:User=Depends(current_user),db:Session=Depends(get_db)):
        return db.scalars(select(TravelGroup).join(Membership,Membership.group_id==TravelGroup.id).where(Membership.user_id==user.id).order_by(TravelGroup.created_at,TravelGroup.id)).all()

    @app.post('/groups/join',response_model=s.GroupOut,tags=['groups'])
    def join(body:s.Join,request:Request,user:User=Depends(current_user),db:Session=Depends(get_db)):
        limited(request,'join')
        group=db.scalar(select(TravelGroup).where(TravelGroup.invite_digest==invite_digest(body.invitation_code)))
        if group is None:raise HTTPException(404,'Invitation not found')
        active(group)
        if db.get(Membership,(group.id,user.id)) is None:
            db.add(Membership(group_id=group.id,user_id=user.id,role='member'));bump(db,group);db.commit()
        return group

    @app.get('/groups/{group_id}',response_model=s.GroupOut,tags=['groups'])
    def get_group(group_id:str,user:User=Depends(current_user),db:Session=Depends(get_db)):
        return member_group(db,group_id,user)

    @app.patch('/groups/{group_id}',response_model=s.GroupOut,tags=['groups'])
    def edit_group(group_id:str,body:s.GroupPatch,user:User=Depends(current_user),db:Session=Depends(get_db)):
        group=owner_group(db,group_id,user)
        if body.name is not None:group.name=body.name
        if body.archived is not None:group.archived=body.archived
        db.commit();return group

    @app.delete('/groups/{group_id}',status_code=204,tags=['groups'])
    def delete_group(group_id:str,user:User=Depends(current_user),db:Session=Depends(get_db)):
        group=owner_group(db,group_id,user);db.delete(group);db.commit();return Response(status_code=204)

    @app.post('/groups/{group_id}/invitation',response_model=s.InvitationOut,tags=['groups'])
    def rotate_invitation(group_id:str,user:User=Depends(current_user),db:Session=Depends(get_db)):
        group=owner_group(db,group_id,user);active(group)
        code,digest=invitation();group.invite_digest=digest;db.commit()
        return {'invitation_code':code}

    @app.get('/groups/{group_id}/members',response_model=list[s.MemberOut],tags=['groups'])
    def members(group_id:str,user:User=Depends(current_user),db:Session=Depends(get_db)):
        member_group(db,group_id,user)
        rows=db.execute(select(Membership,User).join(User,User.id==Membership.user_id).where(Membership.group_id==group_id).order_by(Membership.joined_at,User.id)).all()
        return [s.MemberOut(user_id=u.id,display_name=u.display_name,role=m.role,joined_at=m.joined_at) for m,u in rows]

    @app.get('/groups/{group_id}/planning',response_model=s.PlanningOut,tags=['groups'])
    def planning(group_id:str,request:Request,scope:str='catalog',kind:str='attraction',user:User=Depends(current_user),db:Session=Depends(get_db)):
        member_group(db,group_id,user)
        if scope not in ['catalog','hawaii','pakistan'] or kind not in ['attraction','hotel']:raise HTTPException(422,'Invalid planning scope/kind')
        users=db.scalars(select(User).join(Membership,Membership.user_id==User.id).where(Membership.group_id==group_id).order_by(User.id)).all()
        prefs=db.scalars(select(MemberPreference).where(MemberPreference.group_id==group_id)).all()
        return planning_summary(request.app.state.service,users,prefs,scope,kind)

    @app.delete('/groups/{group_id}/members/{member_id}',status_code=204,tags=['groups'])
    def remove_member(group_id:str,member_id:str,user:User=Depends(current_user),db:Session=Depends(get_db)):
        group=member_group(db,group_id,user)
        if user.id!=group.owner_id and user.id!=member_id:raise HTTPException(403,'Only owner or the member can remove membership')
        if member_id==group.owner_id:raise HTTPException(409,'Transfer ownership or delete the group before the owner leaves')
        membership=db.get(Membership,(group_id,member_id))
        if membership is None:raise HTTPException(404,'Member not found')
        if user.id==group.owner_id:
            # A removed member must not immediately rejoin with their old code.
            # The owner can explicitly issue a fresh shareable invitation.
            _,group.invite_digest=invitation()
        db.delete(membership);bump(db,group);db.commit();return Response(status_code=204)

    @app.post('/groups/{group_id}/transfer-ownership',response_model=s.GroupOut,tags=['groups'])
    def transfer(group_id:str,body:s.Transfer,user:User=Depends(current_user),db:Session=Depends(get_db)):
        group=owner_group(db,group_id,user);active(group)
        target=db.get(Membership,(group_id,body.user_id))
        if target is None:raise HTTPException(422,'New owner must already be a member')
        db.get(Membership,(group_id,user.id)).role='member'
        target.role='owner';group.owner_id=body.user_id
        _,group.invite_digest=invitation()
        db.commit();return group

    @app.put('/groups/{group_id}/preferences/me',response_model=s.PreferenceOut,tags=['preferences'])
    def save_preferences(group_id:str,body:s.Preferences,request:Request,user:User=Depends(current_user),db:Session=Depends(get_db)):
        group=member_group(db,group_id,user);active(group)
        if any(item not in request.app.state.service.by_id for item in body.preferred_destination_ids):
            raise HTTPException(422,'Unknown catalog destination ID')
        row=db.get(MemberPreference,(group_id,user.id))
        if row is None:row=MemberPreference(group_id=group_id,user_id=user.id,values=body.model_dump(mode='json'));db.add(row)
        else:row.values=body.model_dump(mode='json')
        bump(db,group);db.commit()
        return s.PreferenceOut(group_id=group_id,user_id=user.id,values=row.values,updated_at=row.updated_at)

    @app.get('/groups/{group_id}/preferences/me',response_model=s.PreferenceOut,tags=['preferences'])
    def get_preferences(group_id:str,user:User=Depends(current_user),db:Session=Depends(get_db)):
        member_group(db,group_id,user)
        row=db.get(MemberPreference,(group_id,user.id))
        if row is None:raise HTTPException(404,'Preferences not saved')
        return s.PreferenceOut(group_id=group_id,user_id=user.id,values=row.values,updated_at=row.updated_at)

    def create_recommendation(group_id,body,request,user,db,individual):
        group=member_group(db,group_id,user);active(group)
        revision=group.revision
        if individual:
            pref=db.get(MemberPreference,(group_id,user.id));rows=[pref] if pref else []
            expected=1
        else:
            expected=db.scalar(select(func.count()).select_from(Membership).where(Membership.group_id==group_id))
            if expected<2:raise HTTPException(409,'At least two members are required for group consensus')
            rows=db.scalars(select(MemberPreference).where(MemberPreference.group_id==group_id).order_by(MemberPreference.user_id)).all()
        if len(rows)!=expected:raise HTTPException(409,'Every participating member must save their own preferences first')
        try:payload,notices,filters=generate(request.app.state.service,rows,body,individual)
        except (ValueError,OSError):raise HTTPException(503,'Recommendation catalog/model unavailable or incompatible; check server artifacts')
        db.refresh(group)
        if group.revision!=revision:raise HTTPException(409,'Group preferences/membership changed during scoring; retry')
        row=GroupRecommendation(group_id=group_id,created_by=user.id,group_revision=revision,
            method='individual' if individual else body.method,filters=filters,warnings=notices,payload=payload)
        db.add(row);db.commit();return recommendation_out(row,group)

    @app.post('/groups/{group_id}/recommendations',response_model=s.RecommendationOut,status_code=201,tags=['recommendations'])
    def recommend_group(group_id:str,body:s.RecommendationRequest,request:Request,user:User=Depends(current_user),db:Session=Depends(get_db)):
        return create_recommendation(group_id,body,request,user,db,False)

    @app.post('/groups/{group_id}/recommendations/individual',response_model=s.RecommendationOut,status_code=201,tags=['recommendations'])
    def recommend_individual(group_id:str,body:s.RecommendationRequest,request:Request,user:User=Depends(current_user),db:Session=Depends(get_db)):
        return create_recommendation(group_id,body,request,user,db,True)

    @app.get('/groups/{group_id}/recommendations',response_model=list[s.RecommendationOut],tags=['recommendations'])
    def recommendations(group_id:str,user:User=Depends(current_user),db:Session=Depends(get_db)):
        group=member_group(db,group_id,user)
        rows=db.scalars(select(GroupRecommendation).where(GroupRecommendation.group_id==group_id).order_by(GroupRecommendation.created_at.desc(),GroupRecommendation.id)).all()
        return [recommendation_out(row,group) for row in rows]

    @app.get('/groups/{group_id}/recommendations/{rec_id}',response_model=s.RecommendationOut,tags=['recommendations'])
    def get_recommendation(group_id:str,rec_id:str,user:User=Depends(current_user),db:Session=Depends(get_db)):
        group=member_group(db,group_id,user);return recommendation_out(recommendation(db,group,rec_id),group)

    @app.put('/groups/{group_id}/recommendations/{rec_id}/vote',response_model=s.VoteOut,tags=['votes'])
    def vote(group_id:str,rec_id:str,body:s.VoteRequest,user:User=Depends(current_user),db:Session=Depends(get_db)):
        group=member_group(db,group_id,user);active(group)
        row=recommendation(db,group,rec_id,True);require_group_recommendation(row);selected_destination(row,body.destination_id)
        ballot=db.scalar(select(Vote).where(Vote.recommendation_id==rec_id,Vote.user_id==user.id))
        if ballot is None:ballot=Vote(group_id=group_id,recommendation_id=rec_id,user_id=user.id,destination_id=body.destination_id);db.add(ballot)
        else:ballot.destination_id=body.destination_id
        db.commit();return ballot

    @app.delete('/groups/{group_id}/recommendations/{rec_id}/vote',status_code=204,tags=['votes'])
    def withdraw_vote(group_id:str,rec_id:str,user:User=Depends(current_user),db:Session=Depends(get_db)):
        group=member_group(db,group_id,user);active(group);recommendation(db,group,rec_id)
        db.execute(delete(Vote).where(Vote.recommendation_id==rec_id,Vote.user_id==user.id));db.commit();return Response(status_code=204)

    @app.get('/groups/{group_id}/recommendations/{rec_id}/votes',response_model=list[s.VoteCount],tags=['votes'])
    def votes(group_id:str,rec_id:str,user:User=Depends(current_user),db:Session=Depends(get_db)):
        group=member_group(db,group_id,user);row=recommendation(db,group,rec_id)
        counts=dict(db.execute(select(Vote.destination_id,func.count()).where(Vote.recommendation_id==rec_id).group_by(Vote.destination_id)).all())
        return [{'destination_id':r['destination_id'],'votes':counts.get(r['destination_id'],0)} for r in row.payload['results']]

    @app.get('/groups/{group_id}/recommendations/{rec_id}/voting',response_model=s.VotingSummary,tags=['votes'])
    def voting_summary(group_id:str,rec_id:str,user:User=Depends(current_user),db:Session=Depends(get_db)):
        group=member_group(db,group_id,user);row=recommendation(db,group,rec_id)
        ballots=db.scalars(select(Vote).where(Vote.recommendation_id==rec_id)).all()
        by_user={v.user_id:v.destination_id for v in ballots}
        counts={r['destination_id']:0 for r in row.payload['results']}
        for ballot in ballots:counts[ballot.destination_id]+=1
        users=db.scalars(select(User).join(Membership,Membership.user_id==User.id).where(Membership.group_id==group_id).order_by(User.id)).all()
        return {'recommendation_id':rec_id,'eligible_to_vote':not group.archived and row.method!='individual' and row.group_revision==group.revision,
                'total_members':len(users),'total_votes':len(ballots),'own_destination_id':by_user.get(user.id),
                'choices':[{'destination_id':item,'votes':n} for item,n in counts.items()],
                'members':[{'user_id':u.id,'display_name':u.display_name,'destination_id':by_user.get(u.id)} for u in users]}

    @app.get('/groups/{group_id}/itinerary',response_model=list[s.ItineraryOut],tags=['itinerary'])
    def itinerary(group_id:str,user:User=Depends(current_user),db:Session=Depends(get_db)):
        member_group(db,group_id,user)
        return db.scalars(select(ItineraryItem).where(ItineraryItem.group_id==group_id).order_by(ItineraryItem.position)).all()

    @app.post('/groups/{group_id}/itinerary',response_model=s.ItineraryOut,status_code=201,tags=['itinerary'])
    def add_itinerary(group_id:str,body:s.ItineraryCreate,user:User=Depends(current_user),db:Session=Depends(get_db)):
        group=owner_group(db,group_id,user);active(group)
        rec=recommendation(db,group,body.recommendation_id,True)
        require_group_recommendation(rec)
        selected=selected_destination(rec,body.destination_id)
        check_itinerary_date(body.planned_date,db.scalars(select(MemberPreference).where(MemberPreference.group_id==group_id)).all())
        row=ItineraryItem(group_id=group_id,created_by=user.id,destination_snapshot=selected,**body.model_dump())
        db.add(row);db.commit();return row

    @app.patch('/groups/{group_id}/itinerary/{item_id}',response_model=s.ItineraryOut,tags=['itinerary'])
    def edit_itinerary(group_id:str,item_id:str,body:s.ItineraryPatch,user:User=Depends(current_user),db:Session=Depends(get_db)):
        group=owner_group(db,group_id,user);active(group)
        row=db.get(ItineraryItem,item_id)
        if row is None or row.group_id!=group_id:raise HTTPException(404,'Itinerary item not found')
        check_itinerary_date(body.planned_date,db.scalars(select(MemberPreference).where(MemberPreference.group_id==group_id)).all())
        row.position,row.planned_date,row.notes=body.position,body.planned_date,body.notes;db.commit();return row

    @app.delete('/groups/{group_id}/itinerary/{item_id}',status_code=204,tags=['itinerary'])
    def delete_itinerary(group_id:str,item_id:str,user:User=Depends(current_user),db:Session=Depends(get_db)):
        group=owner_group(db,group_id,user);active(group)
        row=db.get(ItineraryItem,item_id)
        if row is None or row.group_id!=group_id:raise HTTPException(404,'Itinerary item not found')
        db.delete(row);db.commit();return Response(status_code=204)

    return app
