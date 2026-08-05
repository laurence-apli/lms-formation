"""
Routes cÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂ´tÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂ© ÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂ©lÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂ¨ve -- toutes dÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂ©pendent de eleve_connecte (un ÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂ©lÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂ¨ve doit ÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂªtre
authentifiÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂ© pour voir quoi que ce soit ici).
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session, selectinload

from ..database import obtenir_session
from ..models import (
    Eleve, Formation, Module, Chapitre, AccesFormation,
    sequence_chapitres, chapitre_dans_le_niveau, chapitre_est_accessible,
    progression_pourcentage, valider_chapitre as valider_chapitre_modele,
    SeanceAccompagnement,
)
from .auth import eleve_connecte
from ..emails import email_coaching_rdv, email_demande_rdv_coach
from .boutique_models import propositions_montee_niveau

router = APIRouter(prefix="/api/eleve", dependencies=[Depends(eleve_connecte)])


@router.get("/tableau-de-bord")
def tableau_de_bord(eleve: Eleve = Depends(eleve_connecte), session: Session = Depends(obtenir_session)):
    formations_acquises = []
    for acces in eleve.acces_formations:
        formation = acces.formation
        if not formation.actif and not eleve.compte_test:
            continue  # formation dÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂ©sactivÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂ©e : invisible cÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂ´tÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂ© ÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂ©lÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂ¨ve, mÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂªme si l'accÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂ¨s existe toujours en base
        formations_acquises.append({
            "id": formation.id, "titre": formation.titre, "couleur": formation.couleur,
            "nb_niveaux": formation.nb_niveaux, "ordre_affichage": formation.ordre_affichage, "niveau": acces.niveau,
            "progression": progression_pourcentage(session, eleve.id, formation),
        })

    formations_acquises.sort(key=lambda f: (0 if f["progression"] > 0 else 1, f["ordre_affichage"]))

    ids_acquis = {f["id"] for f in formations_acquises}
    formations_disponibles = [
        {"id": f.id, "titre": f.titre, "couleur": f.couleur, "ordre_affichage": f.ordre_affichage}
        for f in session.query(Formation).filter_by(actif=True).order_by(Formation.ordre_affichage, Formation.id).all()
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
        raise HTTPException(status_code=403, detail="Vous n'avez pas accÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂ¨s ÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂ  cette formation.")
    if not formation.actif and not eleve.compte_test:
        # VÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂ©rification de sÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂ©curitÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂ© mÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂªme si l'ÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂ©lÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂ¨ve a dÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂ©jÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂ  l'onglet ouvert ou
        # connaÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂ®t l'adresse exacte -- une formation dÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂ©sactivÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂ©e doit rester
        # inaccessible ÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂ  tout moment, pas seulement absente du tableau de bord.
        raise HTTPException(status_code=403, detail="Cette formation n'est actuellement pas disponible.")
    return acces


@router.get("/formations/{formation_id}")
def detail_formation(
    formation_id: int, eleve: Eleve = Depends(eleve_connecte), session: Session = Depends(obtenir_session),
):
    """Renvoie le sommaire complet (modules/chapitres VISIBLES au niveau de
    l'ÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂ©lÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂ¨ve uniquement) -- les ÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂ©lÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂ©ments hors niveau sont totalement absents
    de cette rÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂ©ponse, pas seulement grisÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂ©s cÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂ´tÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂ© affichage."""
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

        if chapitres_visibles:  # un module sans aucun chapitre visible n'apparaÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂ®t pas du tout
            modules_visibles.append({
                "id": module.id, "titre": module.titre, "chapitres": chapitres_visibles,
            })

    jours_cabinet_total = acces.formation.jours_pour_niveau(acces.niveau)
    jours_visio_total = acces.formation.jours_visio_pour_niveau(acces.niveau)
    return {
        'id': formation.id, 'titre': formation.titre,
        'presentation_html': formation.presentation_html,
        'progression': progression_pourcentage(session, eleve.id, formation),
        'modules': modules_visibles,
        'accompagnement_cabinet': {
            'total': jours_cabinet_total,
            'utilises': acces.jours_cabinet_utilises(),
            'restants': acces.jours_cabinet_restants(),
        } if jours_cabinet_total > 0 else None,

        'accompagnement_visio': {
            'total': jours_visio_total,
            'utilises': acces.jours_visio_utilises(),
            'restants': acces.jours_visio_restants(),
        } if jours_visio_total > 0 else None,
        'lien_resalib': eleve.lien_resalib,
        'lien_resalib_visio': eleve.lien_resalib_visio,
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
        raise HTTPException(status_code=403, detail="Ce module n'est pas inclus dans votre niveau d'accÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂ¨s.")

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
    # CORRECTION PERFORMANCE : le chapitre est chargÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂ© avec toute sa formation
    # (modules + chapitres) en une seule fois via selectinload, au lieu de
    # laisser chaque relation se charger une par une (module, puis formation,
    # puis modules de la formation, puis chapitres de chaque module...).
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

    # CORRECTION PERFORMANCE : l'accÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂ¨s ÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂ©lÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂ¨ve (AccesFormation) n'est rÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂ©cupÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂ©rÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂ©
    # qu'UNE fois ici, puis rÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂ©utilisÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂ© -- avant, la mÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂªme requÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂªte ÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂ©tait refaite
    # 3 fois (une dans la vÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂ©rification d'accÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂ¨s, une dans
    # chapitre_est_accessible, une dans progression_pourcentage).
    acces = (
        session.query(AccesFormation)
        .filter_by(eleve_id=eleve.id, formation_id=formation.id)
        .first()
    )
    if acces is None:
        raise HTTPException(status_code=403, detail="Vous n'avez pas accÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂ¨s ÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂ  cette formation.")
    if not formation.actif and not eleve.compte_test:
        raise HTTPException(status_code=403, detail="Cette formation n'est actuellement pas disponible.")

    ok, raison = chapitre_est_accessible(session, eleve.id, chapitre, acces=acces)
    if not ok:
        raise HTTPException(status_code=403, detail=f"Impossible de valider ce chapitre : {raison}")

    valider_chapitre_modele(session, eleve.id, chapitre_id)

    # Si ce chapitre a un lien coaching ÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂ¢ÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂ premiÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂ¨re sÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂÃÂ©ance auto
    if chapitre.lien_coaching:
        seance = SeanceAccompagnement(
            acces_id=acces.id,
            lien_resalib=chapitre.lien_coaching,
            type_envoi="auto",
            statut="en_attente",
        )
        session.add(seance)
        session.commit()
        email_coaching_rdv(
            destinataire=eleve.email,
            prenom=eleve.prenom,
            lien_resalib=chapitre.lien_coaching,
            titre_formation=formation.titre,
    )
    nouvelle_progression = progression_pourcentage(session, eleve.id, formation, acces=acces)
    return {"ok": True, "progression": nouvelle_progression}

@router.get("/montees-de-niveau")
def montees_de_niveau(
    eleve: Eleve = Depends(eleve_connecte),
    session: Session = Depends(obtenir_session),
):
    """Retourne toutes les propositions de mont\u00e9e de niveau pour l'\u00e9l\u00e8ve connect\u00e9,
    toutes formations confondues."""
    return propositions_montee_niveau(session, eleve.id)

@router.post("/formations/{formation_id}/demander-rdv")
async def demander_rdv(
    formation_id: int,
    request: Request,
    eleve: Eleve = Depends(eleve_connecte),
    session: Session = Depends(obtenir_session),
):
    """Envoie un email de confirmation RDV ÃÂ  lÃ¢ÂÂÃÂ©lÃÂ¨ve et ÃÂ  Laurence."""
    donnees = await request.json()
    type_rdv = donnees.get("type", "cabinet")
    acces = session.query(AccesFormation).filter_by(
        eleve_id=eleve.id, formation_id=formation_id
    ).first()
    if not acces:
        raise HTTPException(status_code=404, detail="Formation introuvable.")
    formation = acces.formation
    if type_rdv == "visio":
        lien = formation.lien_visio or eleve.lien_resalib_visio or eleve.lien_resalib or ""
    else:
        lien = eleve.lien_resalib or ""
    email_coaching_rdv(
        destinataire=eleve.email,
        prenom=eleve.prenom,
        lien_resalib=lien or "",
        titre_formation=formation.titre,
    )
    email_demande_rdv_coach(
        prenom_eleve=eleve.prenom,
        nom_eleve=eleve.nom,
        email_eleve=eleve.email,
        type_rdv=type_rdv,
        titre_formation=formation.titre,
    )
    return {"ok": True, "lien": lien}
