"""
Connexion ÃÂ  la base de donnÃÂ©es et fourniture d'une session par requÃÂªte web.
"""
import logging
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from .config import DATABASE_URL
from .models import Base

logger = logging.getLogger(__name__)

# `connect_args` spÃÂ©cifique ÃÂ  SQLite (nÃÂ©cessaire seulement en dÃÂ©veloppement
# local) -- ignorÃÂ© si on utilise PostgreSQL (Neon) en production.
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Colonnes ajoutÃÂ©es au modÃÂ¨le APRÃÂS la crÃÂ©ation initiale des tables.
# Chaque instruction utilise ADD COLUMN IF NOT EXISTS : idempotente, sans danger.
# SQLite ne supporte pas IF NOT EXISTS Ã¢ÂÂ ignorÃÂ©es en dev local.
_MIGRATIONS_COLONNES = [
    "ALTER TABLE eleves ADD COLUMN IF NOT EXISTS nb_connexions INTEGER DEFAULT 0",
    "ALTER TABLE eleves ADD COLUMN IF NOT EXISTS derniere_connexion TIMESTAMP",
    "ALTER TABLE chapitres ADD COLUMN IF NOT EXISTS lien_coaching VARCHAR(500)",
    "ALTER TABLE eleves ADD COLUMN IF NOT EXISTS lien_resalib VARCHAR(500)",
        "ALTER TABLE eleves ADD COLUMN IF NOT EXISTS lien_resalib_visio VARCHAR(500)",
        "ALTER TABLE formations ADD COLUMN IF NOT EXISTS lien_visio VARCHAR(500)",
    "ALTER TABLE seances_accompagnement ADD COLUMN IF NOT EXISTS lien_resalib VARCHAR(500)",
    "ALTER TABLE seances_accompagnement ADD COLUMN IF NOT EXISTS type_envoi VARCHAR(20)",
    "ALTER TABLE seances_accompagnement ADD COLUMN IF NOT EXISTS statut VARCHAR(20) DEFAULT 'en_attente'",
    "ALTER TABLE seances_accompagnement ADD COLUMN IF NOT EXISTS date_realise TIMESTAMP",
    "ALTER TABLE eleves ADD COLUMN IF NOT EXISTS compte_test BOOLEAN DEFAULT FALSE",
    "ALTER TABLE jours_accompagnement_niveau ADD COLUMN IF NOT EXISTS jours_visio INTEGER DEFAULT 0",
    "ALTER TABLE seances_accompagnement ADD COLUMN IF NOT EXISTS type_accompagnement VARCHAR(20) DEFAULT 'cabinet'",
]


def _migrer_colonnes():
    """Applique les migrations de colonnes manquantes (PostgreSQL uniquement)."""
    with engine.connect() as conn:
        for sql in _MIGRATIONS_COLONNES:
            try:
                conn.execute(text(sql))
                conn.commit()
            except Exception as e:
                conn.rollback()
                logger.warning("Migration colonne ignorÃÂ©e (%s) : %s", sql.split()[:6], e)


def initialiser_base():
    """CrÃÂ©e toutes les tables manquantes et ajoute les colonnes ajoutÃÂ©es
    aprÃÂ¨s la crÃÂ©ation initiale. Sans danger ÃÂ  appeler ÃÂ  chaque dÃÂ©marrage."""
    Base.metadata.create_all(bind=engine)
    if not DATABASE_URL.startswith("sqlite"):
        _migrer_colonnes()


def obtenir_session():
    """Fournit une session de base de donnÃÂ©es pour la durÃÂ©e d'une requÃÂªte web,
    et la referme proprement ensuite -- mÃÂªme si une erreur survient."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
