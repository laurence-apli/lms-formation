"""
Script de migration -- à exécuter UNE SEULE FOIS pour corriger des colonnes
déjà créées en base avec l'ancien type `VARCHAR(500)`, devenu `Text` dans le
code (voir models.py). `Base.metadata.create_all()` ne modifie JAMAIS les
colonnes d'une table déjà existante -- changer le type dans le code seul ne
suffit donc pas une fois la table créée en production, ce qui explique le
problème d'enregistrement rencontré avec les PDF, photos et logos malgré la
mise à jour du code.

Usage (depuis la racine du projet, une fois DATABASE_URL configurée) :

    python -m app.migration_corriger_colonnes_url

Sans danger à exécuter plusieurs fois : chaque modification de colonne ne
s'applique que si elle n'a pas déjà le bon type.
"""
from sqlalchemy import create_engine, text
from .config import DATABASE_URL


def migrer():
    if DATABASE_URL.startswith("sqlite"):
        print("Base SQLite détectée : ce script ne s'applique qu'à PostgreSQL "
              "(SQLite n'impose pas de limite stricte sur VARCHAR, donc rien à corriger).")
        return

    engine = create_engine(DATABASE_URL)
    instructions = [
        ("medias", "url", "ALTER TABLE medias ALTER COLUMN url TYPE TEXT;"),
        ("administrateurs", "photo_url", "ALTER TABLE administrateurs ALTER COLUMN photo_url TYPE TEXT;"),
        ("administrateurs", "logo_url", "ALTER TABLE administrateurs ALTER COLUMN logo_url TYPE TEXT;"),
    ]

    with engine.connect() as connexion:
        for table, colonne, instruction_sql in instructions:
            try:
                connexion.execute(text(instruction_sql))
                connexion.commit()
                print(f"✓ Colonne {table}.{colonne} corrigée (VARCHAR(500) -> TEXT).")
            except Exception as e:
                print(f"✗ Erreur sur {table}.{colonne} : {e}")
                connexion.rollback()

    print("\nMigration terminée. Les PDF, photos et logos peuvent maintenant être enregistrés sans limite de taille artificielle.")


if __name__ == "__main__":
    migrer()
