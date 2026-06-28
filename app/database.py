"""
Connexion à la base de données et fourniture d'une session par requête web.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from .config import DATABASE_URL
from .models import Base

# `connect_args` spécifique à SQLite (nécessaire seulement en développement
# local) -- ignoré si on utilise PostgreSQL (Neon) en production.
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def initialiser_base():
    """Crée toutes les tables si elles n'existent pas encore. Sans danger à
    appeler à chaque démarrage : ne touche jamais aux tables déjà existantes."""
    Base.metadata.create_all(bind=engine)


def obtenir_session():
    """Fournit une session de base de données pour la durée d'une requête web,
    et la referme proprement ensuite -- même si une erreur survient."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
