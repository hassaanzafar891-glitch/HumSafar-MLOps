from pathlib import Path

from sqlalchemy import create_engine, event, inspect, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.api.models import Base,SchemaInfo

SCHEMA_VERSION=1


def database(url):
    parsed=make_url(url)
    options={'pool_pre_ping':True}
    if parsed.get_backend_name()=='sqlite':
        options['connect_args']={'check_same_thread':False,'timeout':30}
        if parsed.database in [None,'',':memory:']:
            options['poolclass']=StaticPool
        else:
            Path(parsed.database).parent.mkdir(parents=True,exist_ok=True)
    engine=create_engine(url,**options)
    if parsed.get_backend_name()=='sqlite':
        @event.listens_for(engine,'connect')
        def foreign_keys(connection,_):
            cursor=connection.cursor()
            cursor.execute('PRAGMA foreign_keys=ON')
            cursor.close()
    return engine,sessionmaker(bind=engine,expire_on_commit=False)


def initialize_schema(engine):
    tables=inspect(engine).get_table_names()
    if tables and 'schema_info' not in tables:
        raise RuntimeError('Unversioned database detected; refusing automatic schema changes')
    if not tables:
        Base.metadata.create_all(engine)
        with engine.begin() as connection:
            connection.execute(SchemaInfo.__table__.insert().values(id=1,version=SCHEMA_VERSION))
    verify_schema(engine)


def verify_schema(engine):
    if 'schema_info' not in inspect(engine).get_table_names():
        raise RuntimeError('Database not initialized: run python -m backend.api.init_db')
    with engine.connect() as connection:
        version=connection.execute(select(SchemaInfo.version).where(SchemaInfo.id==1)).scalar_one_or_none()
    if version!=SCHEMA_VERSION or not set(Base.metadata.tables)<=set(inspect(engine).get_table_names()):
        raise RuntimeError('Database schema version mismatch; explicit migration required')
