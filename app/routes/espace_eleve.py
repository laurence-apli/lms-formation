"""
Correction performance -- route de validation de chapitre.
Remplace la route existante dans app/routes/espace_eleve.py.

Ce qui change par rapport à l'original :
1. Le chapitre est chargé avec toute sa formation (modules + chapitres) en une
   seule fois via `selectinload`, au lieu de laisser chaque relation se
   charger une par une (module, puis formation, puis modules de la
   formation, puis chapitres de chaque module...).
2. L'accès élève (AccesFormation) n'est récupéré qu'UNE fois, puis réutilisé
   -- avant, la même requête était refaite 3 fois (une dans la vérification
   d'accès, une dans chapitre_est_accessible, une dans progression_pourcentage).
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, selectinload

from ..database import obtenir_session
from ..models import (
    Eleve, Chapitre, Module, Formation, AccesFormation,
    chapitre_est_accessible, progression_pourcentage,
    valider_chapitre as valider_chapitre_modele,
)
from .auth import eleve_connecte

router = APIRouter(prefix="/eleve", dependencies=[Depends(eleve_connecte)])


@router.post("/chapitres/{chapitre_id}/valider")
def valider_chapitre_eleve(
    chapitre_id: int, eleve: Eleve = Depends(eleve_connecte), session: Session = Depends(obtenir_session),
):
    # 1. Une seule requête qui charge le chapitre ET toute sa formation
    #    (modules + chapitres) d'un coup, au lieu de laisser chaque relation
    #    se charger une par une plus tard dans le code.
    chapitre = (
        session.query(Chapitre)
        .options(
            selectinload(Chapitre.module)
            .selectinload(Module.formation)
            .selectinload(Formation.modules)
            .selectinload(Module.chapitres)
        )
        .filter(Chapitre.id == chapitre_id)
        .first()
    )
    if chapitre is None:
        raise HTTPException(status_code=404, detail="Chapitre introuvable.")

    formation = chapitre.module.formation

    # 2. Une seule requête pour l'accès élève -- réutilisée ensuite partout,
    #    au lieu d'être refaite à chaque fonction appelée.
    acces = (
        session.query(AccesFormation)
        .filter_by(eleve_id=eleve.id, formation_id=formation.id)
        .first()
    )
    if acces is None:
        raise HTTPException(status_code=403, detail="Vous n'avez pas accès à cette formation.")

    ok, raison = chapitre_est_accessible(session, eleve.id, chapitre, acces=acces)
    if not ok:
        raise HTTPException(status_code=403, detail=f"Impossible de valider ce chapitre : {raison}")

    valider_chapitre_modele(session, eleve.id, chapitre_id)
    nouvelle_progression = progression_pourcentage(session, eleve.id, formation, acces=acces)
    return {"ok": True, "progression": nouvelle_progression}
