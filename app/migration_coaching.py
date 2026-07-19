"""
Migration : ajout des colonnes de coaching sur les tables existantes.

Nouveautés :
- chapitres.lien_coaching       VARCHAR(500) nullable
- seances_accompagnement.lien_resalib   VARCHAR(500) nullable
- seances_accompagnement.type_envoi     VARCHAR(20)  nullable  ('auto' | 'manuel')
- seances_accompagnement.statut         VARCHAR(20)  NOT NULL DEFAULT 'en_attente'
- seances_accompagnement.date_realise   TIMESTAMP    nullable

Usage : python -m app.migration_coaching
"""
from sqlalchemy import create_engine, text
from .config import DATABASE_URL


def migrer():
    engine = create_engine(DATABASE_URL)

    migrations = [
        (
            "chapitres",
            "lien_coaching",
            "ALTER TABLE chapitres ADD COLUMN IF NOT EXISTS lien_coaching VARCHAR(500);",
        ),
        (
            "seances_accompagnement",
            "lien_resalib",
            "ALTER TABLE seances_accompagnement ADD COLUMN IF NOT EXISTS lien_resalib VARCHAR(500);",
        ),
        (
            "seances_accompagnement",
            "type_envoi",
            "ALTER TABLE seances_accompagnement ADD COLUMN IF NOT EXISTS type_envoi VARCHAR(20);",
        ),
        (
            "seances_accompagnement",
            "statut",
            "ALTER TABLE seances_accompagnement ADD COLUMN IF NOT EXISTS statut VARCHAR(20) NOT NULL DEFAULT 'en_attente';",
        ),
        (
            "seances_accompagnement",
            "date_realise",
            "ALTER TABLE seances_accompagnement ADD COLUMN IF NOT EXISTS date_realise TIMESTAMP;",
        ),
    ]

    with engine.connect() as connexion:
        for table, colonne, sql in migrations:
            try:
                connexion.execute(text(sql))
                connexion.commit()
                print(f"  ✓ {table}.{colonne} ajouté")
            except Exception as e:
                print(f"  ✗ {table}.{colonne} : {e}")

    print("Migration coaching terminée.")


if __name__ == "__main__":
    migrer()
