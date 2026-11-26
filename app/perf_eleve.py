"""Calculs groupés pour l'espace élève (performance, nov. 2026).

Chaque requête vers Neon coûte ~150 ms depuis Render. Le tableau de bord et le
sommaire d'une formation faisaient une requête par formation / par chapitre
(plus de 150 allers-retours). Ici tout est chargé en quelques requêtes, puis
calculé en Python — avec exactement les mêmes règles que models.py :
  - progression_pourcentage  -> progression()
  - chapitre_est_accessible  -> etats_chapitres()
"""
from sqlalchemy.orm import Session, selectinload, undefer

from .models import (
    Formation, Module, ValidationChapitre,
    chapitre_dans_le_niveau, sequence_chapitres,
)


def charger_formations(session: Session, ids, avec_image: bool = False) -> dict:
    """{id: Formation} avec modules et chapitres préchargés (3 requêtes au total)."""
    ids = list(set(ids))
    if not ids:
        return {}
    options = [selectinload(Formation.modules).selectinload(Module.chapitres)]
    if avec_image:
        options.append(undefer(Formation.image_url))
    formations = session.query(Formation).options(*options).filter(Formation.id.in_(ids)).all()
    return {f.id: f for f in formations}


def ids_chapitres_valides(session: Session, eleve_id: int) -> set:
    """Tous les chapitres validés par l'élève (1 requête)."""
    return {
        cid for (cid,) in session.query(ValidationChapitre.chapitre_id)
        .filter(ValidationChapitre.eleve_id == eleve_id).all()
    }


def progression(formation: Formation, niveau: int, valides: set) -> float:
    """Même calcul que models.progression_pourcentage, sans requête."""
    visibles = [c for c in sequence_chapitres(formation) if chapitre_dans_le_niveau(formation, niveau, c)]
    if not visibles:
        return 0.0
    nb = sum(1 for c in visibles if c.id in valides)
    return round(100 * nb / len(visibles), 1)


def etats_chapitres(formation: Formation, niveau: int, valides: set) -> dict:
    """{chapitre_id: accessible} pour les chapitres du niveau de l'élève.
    Même règle que models.chapitre_est_accessible : un chapitre est accessible si le
    chapitre précédent (dans le niveau de l'élève) est validé, ou s'il est le premier."""
    etats = {}
    precedent = None
    for c in sequence_chapitres(formation):
        if not chapitre_dans_le_niveau(formation, niveau, c):
            continue
        etats[c.id] = precedent is None or precedent.id in valides
        precedent = c
    return etats
