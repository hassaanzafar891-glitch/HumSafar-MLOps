from datetime import datetime,timedelta,timezone
import hashlib
import secrets
import uuid

import jwt
from pwdlib import PasswordHash

PASSWORDS=PasswordHash.recommended()
DUMMY_HASH=PASSWORDS.hash(secrets.token_urlsafe(32))


def verify_password(password,stored_hash):
    if not isinstance(password,str) or len(password)>128:
        return False
    try:return PASSWORDS.verify(password,stored_hash)
    except (ValueError,TypeError):return False


def invitation():
    code=secrets.token_urlsafe(32)
    return code,invite_digest(code)


def invite_digest(code):return hashlib.sha256(code.encode('utf-8')).hexdigest()


def access_token(user,settings):
    now=datetime.now(timezone.utc)
    return jwt.encode({'sub':user.id,'ver':user.token_version,'iat':now,
        'exp':now+timedelta(minutes=settings.access_token_minutes),'jti':str(uuid.uuid4()),
        'iss':settings.jwt_issuer,'aud':settings.jwt_audience},settings.jwt_secret,algorithm='HS256')


def decode_token(token,settings):
    return jwt.decode(token,settings.jwt_secret,algorithms=['HS256'],issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,options={'require':['sub','ver','iat','exp','jti','iss','aud']})
