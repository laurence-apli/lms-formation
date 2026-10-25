"""
Connexion à la base de données et fourniture d'une session par requête web.
"""
import logging
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from .config import DATABASE_URL
from .models import Base

logger = logging.getLogger(__name__)

# `connect_args` spécifique à SQLite (nécessaire seulement en développement
# local) -- ignoré si on utilise PostgreSQL (Neon) en production.
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Colonnes ajoutées au modèle APRÈS la création initiale des tables.
# Chaque instruction utilise ADD COLUMN IF NOT EXISTS : idempotente, sans danger.
# SQLite ne supporte pas IF NOT EXISTS → ignorées en dev local.
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
    "ALTER TABLE offres ADD COLUMN IF NOT EXISTS badge VARCHAR(200) DEFAULT 'Accompagnement féminin'",
    "ALTER TABLE commandes ADD COLUMN IF NOT EXISTS offre_id INTEGER",
    "ALTER TABLE commandes ADD COLUMN IF NOT EXISTS type_paiement VARCHAR(20)",
    "ALTER TABLE commandes ADD COLUMN IF NOT EXISTS note TEXT",
    "ALTER TABLE commandes ADD COLUMN IF NOT EXISTS montant_prix_total NUMERIC(10,2)",
    "ALTER TABLE jours_accompagnement_niveau ADD COLUMN IF NOT EXISTS jours_visio INTEGER DEFAULT 0",
    "ALTER TABLE seances_accompagnement ADD COLUMN IF NOT EXISTS type_accompagnement VARCHAR(20) DEFAULT 'cabinet'",
    "ALTER TABLE formations ADD COLUMN IF NOT EXISTS acces_auto BOOLEAN DEFAULT FALSE",
    # --- AGENDA (ajouté oct. 2026) ---
    # Les tables agenda_* sont des nouvelles tables créées par create_all,
    # pas de ALTER TABLE nécessaire pour elles.
    # Colonne de liaison sur seances_accompagnement : réservation native
    "ALTER TABLE seances_accompagnement ADD COLUMN IF NOT EXISTS reservation_id INTEGER",
    # Temps de repos après séance (ajouté oct. 2026)
    "ALTER TABLE agenda_types_seances ADD COLUMN IF NOT EXISTS pause_apres_minutes INTEGER DEFAULT 0",
    # Période de validité des plages récurrentes (ajouté oct. 2026)
    "ALTER TABLE agenda_plages_disponibilites ADD COLUMN IF NOT EXISTS valide_du TIMESTAMP",
    "ALTER TABLE agenda_plages_disponibilites ADD COLUMN IF NOT EXISTS valide_au TIMESTAMP",
    # La table agenda_indisponibilites est nouvelle → créée par create_all, pas de ALTER TABLE.
    # Format individuelle/collective + places max (ajouté oct. 2026)
    "ALTER TABLE agenda_types_seances ADD COLUMN IF NOT EXISTS format_seance VARCHAR(20) DEFAULT 'individuelle'",
    "ALTER TABLE agenda_types_seances ADD COLUMN IF NOT EXISTS nb_places_max INTEGER",
    # Tarification + Stripe (ajouté oct. 2026)
    "ALTER TABLE agenda_types_seances ADD COLUMN IF NOT EXISTS prix NUMERIC(10,2)",
    "ALTER TABLE agenda_types_seances ADD COLUMN IF NOT EXISTS mode_paiement VARCHAR(20) DEFAULT 'sans_paiement'",
    "ALTER TABLE agenda_reservations ADD COLUMN IF NOT EXISTS stripe_checkout_session_id VARCHAR(200)",
    "ALTER TABLE agenda_reservations ADD COLUMN IF NOT EXISTS prix_paye NUMERIC(10,2)",
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
                logger.warning("Migration colonne ignorée (%s) : %s", sql.split()[:6], e)


def initialiser_base():
    """Crée toutes les tables manquantes et ajoute les colonnes ajoutées
    après la création initiale. Sans danger à appeler à chaque démarrage."""
    Base.metadata.create_all(bind=engine)
    if not DATABASE_URL.startswith("sqlite"):
        _migrer_colonnes()


def obtenir_session():
    """Fournit une session de base de données pour la durée d'une requête web,
    et la referme proprement ensuite -- même si une erreur survient."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
