"""
Routes côté élève -- toutes dépendent de eleve_connecte (un élève doit être
authentifié pour voir quoi que ce soit ici).
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session, selectinload

from ..database import obtenir_session
from ..models import (
    Eleve, Formation, Module, Chapitre, AccesFormation, MediaModule, MediaFormation,
    sequence_chapitres, chapitre_dans_le_niveau, chapitre_est_accessible,
    progression_pourcentage, valider_chapitre as valider_chapitre_modele,
    SeanceAccompagnement,
)
from .auth import eleve_connecte
from ..resalib import RESALIB_SUIVI
import json
from datetime import datetime
from typing import List
from pydantic import BaseModel
from ..models import ReponseChapitre, ValidationChapitre
from ..emails import email_reponses_chapitre
from .medias_fichiers import media_json
from ..emails import email_coaching_rdv, email_demande_rdv_coach
from .boutique_models import propositions_montee_niveau

router = APIRouter(prefix="/api/eleve", dependencies=[Depends(eleve_connecte)])


@router.get("/tableau-de-bord")
def tableau_de_bord(eleve: Eleve = Depends(eleve_connecte), session: Session = Depends(obtenir_session)):
    formations_acquises = []
    for acces in eleve.acces_formations:
        formation = acces.formation
        if not formation.actif and not eleve.compte_test:
            continue  # formation désactivée : invisible côté élève, même si l'accès existe toujours en base
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
        raise HTTPException(status_code=403, detail="Vous n'avez pas accès à cette formation.")
    if not formation.actif and not eleve.compte_test:
        # Vérification de sécurité même si l'élève a déjà l'onglet ouvert ou
        # connaît l'adresse exacte -- une formation désactivée doit rester
        # inaccessible à tout moment, pas seulement absente du tableau de bord.
        raise HTTPException(status_code=403, detail="Cette formation n'est actuellement pas disponible.")
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
        # Séances de suivi comprises : réservation directe dans Resalib (seul agenda utilisé)
        'rdv_suivi': RESALIB_SUIVI if (jours_cabinet_total > 0 or jours_visio_total > 0) else None,
    'medias': [
        media_json('formation', m)
        for m in formation.medias
    ],
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

    return {"id": module.id, "titre": module.titre, "presentation_html": module.presentation_html,
            "medias": [media_json("module", m) for m in module.medias]}


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
        media_json("chapitre", m)
        for m in chapitre.medias
    ]
    return {
        "id": chapitre.id, "titre": chapitre.titre, "contenu_html": chapitre.contenu_html,
        "valide": deja_valide, "medias": medias,
    }


# ---------- Outils réservés aux comptes test ----------

def _formation_compte_test(formation_id: int, eleve: Eleve, session: Session):
    if not eleve.compte_test:
        raise HTTPException(status_code=403, detail="Réservé aux comptes test.")
    formation = session.get(Formation, formation_id)
    if formation is None:
        raise HTTPException(status_code=404, detail="Formation introuvable.")
    acces = _verifier_acces_formation(eleve, formation, session)
    return formation, acces


@router.post("/formations/{formation_id}/test/tout-valider")
def test_tout_valider(formation_id: int, eleve: Eleve = Depends(eleve_connecte),
                      session: Session = Depends(obtenir_session)):
    """Compte test : valide d'un coup tous les chapitres (de tous les modules) accessibles à son niveau."""
    formation, acces = _formation_compte_test(formation_id, eleve, session)
    deja = {v.chapitre_id for v in session.query(ValidationChapitre).filter_by(eleve_id=eleve.id)}
    nb = 0
    for c in sequence_chapitres(formation):
        if c.id not in deja and chapitre_dans_le_niveau(formation, acces.niveau, c):
            session.add(ValidationChapitre(eleve_id=eleve.id, chapitre_id=c.id))
            nb += 1
    session.commit()
    return {"ok": True, "valides": nb}


@router.post("/formations/{formation_id}/test/reinitialiser")
def test_reinitialiser(formation_id: int, eleve: Eleve = Depends(eleve_connecte),
                       session: Session = Depends(obtenir_session)):
    """Compte test : remet la formation à zéro (validations + réponses aux questionnaires)."""
    formation, _ = _formation_compte_test(formation_id, eleve, session)
    ids = [c.id for m in formation.modules for c in m.chapitres]
    if ids:
        session.query(ValidationChapitre).filter(
            ValidationChapitre.eleve_id == eleve.id, ValidationChapitre.chapitre_id.in_(ids)
        ).delete(synchronize_session=False)
        session.query(ReponseChapitre).filter(
            ReponseChapitre.eleve_id == eleve.id, ReponseChapitre.chapitre_id.in_(ids)
        ).delete(synchronize_session=False)
    session.commit()
    return {"ok": True}


# ---------- Questionnaire de chapitre (cases ☐ et pointillés du Word) ----------

class _ItemReponse(BaseModel):
    type: str
    libelle: str = ""
    coche: bool = False
    question: str = ""
    valeur: str = ""


class _CorpsReponses(BaseModel):
    items: List[_ItemReponse] = []
    envoyer: bool = False


def _chapitre_pour_reponses(chapitre_id: int, eleve: Eleve, session: Session) -> Chapitre:
    chapitre = session.get(Chapitre, chapitre_id)
    if chapitre is None:
        raise HTTPException(status_code=404, detail="Chapitre introuvable.")
    _verifier_acces_formation(eleve, chapitre.module.formation, session)
    return chapitre


@router.get("/chapitres/{chapitre_id}/reponses")
def lire_reponses_chapitre(chapitre_id: int, eleve: Eleve = Depends(eleve_connecte),
                           session: Session = Depends(obtenir_session)):
    _chapitre_pour_reponses(chapitre_id, eleve, session)
    rep = session.query(ReponseChapitre).filter_by(eleve_id=eleve.id, chapitre_id=chapitre_id).first()
    if rep is None:
        return {"items": [], "envoye_le": None}
    return {"items": json.loads(rep.reponses or "[]"),
            "envoye_le": rep.envoye_le.isoformat() if rep.envoye_le else None}


@router.post("/chapitres/{chapitre_id}/reponses")
def enregistrer_reponses_chapitre(chapitre_id: int, corps: _CorpsReponses,
                                  eleve: Eleve = Depends(eleve_connecte),
                                  session: Session = Depends(obtenir_session)):
    chapitre = _chapitre_pour_reponses(chapitre_id, eleve, session)
    items = []
    for it in corps.items[:100]:
        if it.type == "case":
            items.append({"type": "case", "libelle": it.libelle[:500], "coche": bool(it.coche)})
        elif it.type == "texte":
            items.append({"type": "texte", "question": it.question[:500], "valeur": it.valeur[:5000]})
    rempli = any((i["type"] == "case" and i["coche"]) or (i["type"] == "texte" and i["valeur"].strip()) for i in items)

    rep = session.query(ReponseChapitre).filter_by(eleve_id=eleve.id, chapitre_id=chapitre_id).first()
    if rep is None:
        rep = ReponseChapitre(eleve_id=eleve.id, chapitre_id=chapitre_id)
        session.add(rep)
    rep.reponses = json.dumps(items, ensure_ascii=False)
    rep.maj_le = datetime.utcnow()

    email_envoye = False
    if corps.envoyer and rempli:
        email_envoye = email_reponses_chapitre(
            eleve.prenom or "", eleve.nom or "", eleve.email or "",
            chapitre.module.formation.titre, chapitre.titre, items)
        if email_envoye:
            rep.envoye_le = datetime.utcnow()
    session.commit()
    return {"ok": True, "email_envoye": email_envoye, "rempli": rempli}


@router.post("/chapitres/{chapitre_id}/valider")
def valider_chapitre_eleve(
    chapitre_id: int, eleve: Eleve = Depends(eleve_connecte), session: Session = Depends(obtenir_session),
):
    # CORRECTION PERFORMANCE : le chapitre est chargé avec toute sa formation
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

    # CORRECTION PERFORMANCE : l'accès élève (AccesFormation) n'est récupéré
    # qu'UNE fois ici, puis réutilisé -- avant, la même requête était refaite
    # 3 fois (une dans la vérification d'accès, une dans
    # chapitre_est_accessible, une dans progression_pourcentage).
    acces = (
        session.query(AccesFormation)
        .filter_by(eleve_id=eleve.id, formation_id=formation.id)
        .first()
    )
    if acces is None:
        raise HTTPException(status_code=403, detail="Vous n'avez pas accès à cette formation.")
    if not formation.actif and not eleve.compte_test:
        raise HTTPException(status_code=403, detail="Cette formation n'est actuellement pas disponible.")

    ok, raison = chapitre_est_accessible(session, eleve.id, chapitre, acces=acces)
    if not ok:
        raise HTTPException(status_code=403, detail=f"Impossible de valider ce chapitre : {raison}")

    valider_chapitre_modele(session, eleve.id, chapitre_id)

    # Si ce chapitre a un lien coaching → première séance auto
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
def demander_rdv(
    formation_id: int,
    eleve: Eleve = Depends(eleve_connecte),
    session: Session = Depends(obtenir_session),
):
    """Ancien bouton « Prendre RDV » : renvoie simplement le lien Resalib de la séance
    de suivi (plus d'e-mails ni de lien par élève : tout passe par Resalib)."""
    acces = session.query(AccesFormation).filter_by(eleve_id=eleve.id, formation_id=formation_id).first()
    if not acces:
        raise HTTPException(status_code=404, detail="Formation introuvable.")
    return {"ok": True, "lien": RESALIB_SUIVI}
