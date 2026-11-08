from backend.api.config import Settings
from backend.api.database import database,initialize_schema


def main():
    settings=Settings.from_env(require_secret=False)
    engine,_=database(settings.database_url)
    try:initialize_schema(engine)
    finally:engine.dispose()
    print('HumSafar schema v1 initialized/verified. No user or ML data was seeded.')


if __name__=='__main__':main()
