"""Isolated browser-test app. No demo data enters the default app database."""
import secrets
import sys
import tempfile
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
import uvicorn
from backend.api.app import create_app
from backend.api.config import Settings

if __name__=='__main__':
    with tempfile.TemporaryDirectory(prefix='humsafar_browser_') as directory:
        settings=Settings('sqlite:///'+(Path(directory)/'browser.db').as_posix(),secrets.token_urlsafe(48))
        uvicorn.run(create_app(settings),host='127.0.0.1',port=8765,log_level='warning')
