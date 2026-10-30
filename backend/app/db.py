"""DB SQLAlchemy 2.x — DATABASE_URL del entorno, create_all al iniciar."""
from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models import CATEGORIAS_FIJAS, Base, Categoria

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./facturas.db")

_connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as s:
        for nombre in CATEGORIAS_FIJAS:
            if s.get(Categoria, nombre) is None:
                s.add(Categoria(nombre=nombre))
        s.commit()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
