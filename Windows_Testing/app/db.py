import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

DATA_ROOT = Path(os.environ.get("WEBABLE_DATA_DIR", "data")).expanduser().resolve()
DATA_ROOT.mkdir(parents=True, exist_ok=True)

_db_file = (DATA_ROOT / "webable_app.db").resolve()
DATABASE_URL = "sqlite:///" + _db_file.as_posix()

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
