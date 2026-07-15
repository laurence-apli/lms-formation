"""
Route web TEMPORAIRE pour exécuter la migration de colonnes sans avoir besoin
d'un accès Shell (non disponible sur le plan gratuit de Render -- même
contrainte déjà rencontrée pour la création du premier compte administrateur).

Protégée par la même clé secrète que setup_temporaire.py. Sans danger à
laisser en place : la migration elle-même ne fait rien si les colonnes ont
déjà le bon type, donc rappeler cette page plusieurs fois ne casse rien.
"""
from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy import create_engine, text

from .config import DATABASE_URL
from .setup_temporaire import CLE_SECRETE_SETUP

router = APIRouter()


@router.get("/migration-colonnes/{cle}", response_class=PlainTextResponse)
def executer_migration(cle: str):
    if cle != CLE_SECRETE_SETUP:
        raise HTTPException(status_code=404, detail="Page introuvable.")

    if DATABASE_URL.startswith("sqlite"):
        return "Base SQLite détectée : rien à migrer (cette migration ne concerne que PostgreSQL)."

    engine = create_engine(DATABASE_URL)
    instructions = [
        ("medias", "url", "ALTER TABLE medias ALTER COLUMN url TYPE TEXT;"),
        ("administrateurs", "photo_url", "ALTER TABLE administrateurs ALTER COLUMN photo_url TYPE TEXT;"),
        ("administrateurs", "logo_url", "ALTER TABLE administrateurs ALTER COLUMN logo_url TYPE TEXT;"),
        ("formations", "image_url", "ALTER TABLE formations ADD COLUMN IF NOT EXISTS image_url TEXT;"),
        ("formations", "description_courte", "ALTER TABLE formations ADD COLUMN IF NOT EXISTS description_courte TEXT;"),
    ]

    resultats = []
    with engine.connect() as connexion:
        for table, colonne, instruction_sql in instructions:
            try:
                connexion.execute(text(instruction_sql))
                connexion.commit()
                resultats.append(f"OK -- {table}.{colonne} corrigée (VARCHAR(500) -> TEXT).")
            except Exception as e:
                connexion.rollback()
                resultats.append(f"ERREUR sur {table}.{colonne} : {e}")

    resultats.append("\nMigration terminée. Les PDF, photos et logos peuvent maintenant être enregistrés sans limite de taille artificielle.")
    return "\n".join(resultats)
