"""
Routes côté élève -- toutes dépendent de eleve_connecte (un élève doit être
authentifié pour voir quoi que ce soit ici).
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import obtenir_session
from ..models import (
    Eleve, Formation, Module, Chapitre, AccesFormation,
    sequence_chapitres, chapitre_dans_le_niveau, chapitre_est_accessible,
    progression_pourcentage, valider_chapitre as valider_chapitre_modele,
)
from .auth import eleve_connecte

router = APIRouter(prefix="/api/eleve", dependencies=[Depends(eleve_connecte)])


@router.get("/tableau-de-bord")
def tableau_de_bord(eleve: Eleve = Depends(eleve_connecte), session: Session = Depends(obtenir_session)):
    formations_acquises = []
    for acces in eleve.acces_formations:
        formation = acces.formation
        formations_acquises.append({
            "id": formation.id, "titre": formation.titre, "couleur": formation.couleur,
            "nb_niveaux": formation.nb_niveaux, "niveau": acces.niveau,
            "progression": progression_pourcentage(session, eleve.id, formation),
        })

    ids_acquis = {f["id"] for f in formations_acquises}
    formations_disponibles = [
        {"id": f.id, "titre": f.titre, "couleur": f.couleur}
        for f in session.query(Formation).filter_by(actif=True).all()
        if f.id not in ids_acquis
    ]

    return {
        "eleve": {"id": eleve.id, "prenom": eleve.prenom, "nom": eleve.nom, "actif": eleve.actif},
        "formations_acquises": formations_acquises,
        "formations_disponibles": formations_disponibles,
    }


def _verifier_acces_formation(eleve: Eleve, formation: Formation, session: Session) -> AccesFormation:
    acces = (
        session.query(AccesFormation)
        .filter_by(eleve_id=eleve.id, formation_id=formation.id)
        .first()
    )
    if acces is None:
        raise HTTPException(status_code=403, detail="Vous n'avez pas accès à cette formation.")
    return acces


@router.get("/formations/{formation_id}")
def detail_formation(
    formation_id: int, eleve: Eleve = Depends(eleve_connecte), session: Session = Depends(obtenir_session),
):
    """Renvoie le sommaire complet (modules/chapitres VISIBLES au niveau de
    l'élève uniquement) -- les éléments hors niveau sont totalement absents
    de cette réponse, pas seulement grisés côté affichage."""
    formation = session.get(Formation, formation_id)
    if formation is None:
        raise HTTPException(status_code=404, detail="Formation introuvable.")
    acces = _verifier_acces_formation(eleve, formation, session)

    modules_visibles = []
    for module in formation.modules:
        if formation.nb_niveaux > 1 and acces.niveau < module.niveau_requis:
            continue  # module hors niveau : totalement invisible

        chapitres_visibles = []
        for chapitre in module.chapitres:
            if not chapitre_dans_le_niveau(formation, acces.niveau, chapitre):
                continue  # chapitre hors niveau : totalement invisible

            ok, _ = chapitre_est_accessible(session, eleve.id, chapitre)
            deja_valide = any(v.chapitre_id == chapitre.id for v in eleve.validations)
            chapitres_visibles.append({
                "id": chapitre.id, "titre": chapitre.titre,
                "accessible": ok, "valide": deja_valide,
            })

        if chapitres_visibles:  # un module sans aucun chapitre visible n'apparaît pas du tout
            modules_visibles.append({
                "id": module.id, "titre": module.titre, "chapitres": chapitres_visibles,
            })

    jours_total = formation.jours_pour_niveau(acces.niveau)
    return {
        "id": formation.id, "titre": formation.titre,
        "presentation_html": formation.presentation_html,
        "progression": progression_pourcentage(session, eleve.id, formation),
        "modules": modules_visibles,
        "accompagnement": {
            "total": jours_total,
            "restants": acces.jours_accompagnement_restants(),
        } if jours_total > 0 else None,
    }


@router.get("/modules/{module_id}")
def detail_module(
    module_id: int, eleve: Eleve = Depends(eleve_connecte), session: Session = Depends(obtenir_session),
):
    module = session.get(Module, module_id)
    if module is None:
        raise HTTPException(status_code=404, detail="Module introuvable.")
    formation = module.formation
    acces = _verifier_acces_formation(eleve, formation, session)

    if formation.nb_niveaux > 1 and acces.niveau < module.niveau_requis:
        raise HTTPException(status_code=403, detail="Ce module n'est pas inclus dans votre niveau d'accès.")

    return {"id": module.id, "titre": module.titre, "presentation_html": module.presentation_html}


@router.get("/chapitres/{chapitre_id}")
def detail_chapitre(
    chapitre_id: int, eleve: Eleve = Depends(eleve_connecte), session: Session = Depends(obtenir_session),
):
    chapitre = session.get(Chapitre, chapitre_id)
    if chapitre is None:
        raise HTTPException(status_code=404, detail="Chapitre introuvable.")
    formation = chapitre.module.formation
    _verifier_acces_formation(eleve, formation, session)

    ok, raison = chapitre_est_accessible(session, eleve.id, chapitre)
    deja_valide = any(v.chapitre_id == chapitre.id for v in eleve.validations)

    if not ok and not deja_valide:
        raise HTTPException(status_code=403, detail=f"Chapitre non accessible : {raison}")

    medias = [
        {"id": m.id, "type": m.type, "titre": m.titre, "url": m.url, "telechargeable": m.telechargeable}
        for m in chapitre.medias
    ]
    return {
        "id": chapitre.id, "titre": chapitre.titre, "contenu_html": chapitre.contenu_html,
        "valide": deja_valide, "medias": medias,
    }


@router.post("/chapitres/{chapitre_id}/valider")
def valider_chapitre_eleve(
    chapitre_id: int, eleve: Eleve = Depends(eleve_connecte), session: Session = Depends(obtenir_session),
):
    chapitre = session.get(Chapitre, chapitre_id)
    if chapitre is None:
        raise HTTPException(status_code=404, detail="Chapitre introuvable.")
    formation = chapitre.module.formation
    _verifier_acces_formation(eleve, formation, session)

    ok, raison = chapitre_est_accessible(session, eleve.id, chapitre)
    if not ok:
        raise HTTPException(status_code=403, detail=f"Impossible de valider ce chapitre : {raison}")

    valider_chapitre_modele(session, eleve.id, chapitre_id)
    nouvelle_progression = progression_pourcentage(session, eleve.id, formation)
    return {"ok": True, "progression": nouvelle_progression}
