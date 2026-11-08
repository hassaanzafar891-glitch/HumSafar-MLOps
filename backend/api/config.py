from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT=Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    database_url: str
    jwt_secret: str
    access_token_minutes: int = 30
    auto_init_db: bool = True
    jwt_issuer: str = 'humsafar'
    jwt_audience: str = 'humsafar-api'

    def validate(self):
        if len(self.jwt_secret)<32 or self.jwt_secret.lower().startswith(('replace','change-me')):
            raise ValueError('JWT_SECRET_KEY must be a generated secret of at least 32 characters')
        if not 1<=self.access_token_minutes<=1440:
            raise ValueError('ACCESS_TOKEN_MINUTES must be between 1 and 1440')
        if not self.database_url.startswith(('sqlite:','postgresql')):
            raise ValueError('Only SQLite and PostgreSQL database URLs are supported')
        return self

    @classmethod
    def from_env(cls,require_secret=True):
        load_dotenv(ROOT/'.env',override=False)
        result=cls(os.getenv('DATABASE_URL',f"sqlite:///{(ROOT/'backend/var/humsafar.db').as_posix()}"),
                   os.getenv('JWT_SECRET_KEY',''),int(os.getenv('ACCESS_TOKEN_MINUTES','30')),
                   os.getenv('AUTO_INIT_DB','true').lower()=='true')
        return result.validate() if require_secret else result
