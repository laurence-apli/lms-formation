"""
Routes de gestion des Ã©lÃ¨ves -- rÃ©servÃ©es Ã  l'administrateur connectÃ©.
Couvre : fiche Ã©lÃ¨ve centrale, accÃ¨s aux formations avec niveau, jours
d'accompagnement, diplÃ´mes, et la crÃ©ation de compte avec envoi d'e-mail
automatique de premiÃ¨re connexion.
"""
import re
from datetime import datetime
from fastapi import APIRouter, Depends, Form, HTTPException
from sqlalchemy.orm import Session

from ..database import obtenir_session
from ..models import (
    Eleve, Formation, AccesFormation, SeanceAccompagnement,
    ValidationChapitre, progression_pourcentage,
)
from .auth import admin_connecte, creer_token_premiere_connexion
from ..emails import email_coaching_rdv

router = APIRouter(prefix="/admin", dependencies=[Depends(admin_connecte)])

REGEX_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

def _valider_champs_eleve(nom: str, prenom: str, email: str) -> list:
    erreurs = []
    if not nom or not nom.strip():
        erreurs.append("le nom")
    if not prenom or not prenom.strip():
        erreurs.append("le prÃ©nom")
    if not email or not email.strip():
        erreurs.append("l'e-mail")
    elif not REGEX_EMAIL.match(email.strip()):
        erreurs.append("un e-mail valide")
    return erreurs

@router.get("/eleves")
def lister_eleves(session: Session = Depends(obtenir_session)):
    eleves = session.query(Eleve).all()
    return [
        {
            "id": e.id, "nom": e.nom, "prenom": e.prenom, "email": e.email,
            "actif": e.actif, "nb_formations": len(e.acces_formations),
        }
        for e in eleves
    ]

@router.post("/eleves")
def creer_eleve(
    nom: str = Form(...), prenom: str = Form(...), email: str = Form(...),
    session: Session = Depends(obtenir_session),
):
    erreurs = _valider_champs_eleve(nom, prenom, email)
    if erreurs:
        raise HTTPException(status_code=400, detail=f"Champs requis manquants ou invalides : {', '.join(erreurs)}.")

    email_normalise = email.strip().lower()
    if session.query(Eleve).filter_by(email=email_normalise).first() is not None:
        raise HTTPException(status_code=400, detail="Un Ã©lÃ¨ve existe dÃ©jÃ  avec cet e-mail.")

    eleve = Eleve(nom=nom.strip(), prenom=prenom.strip(), email=email_normalise, actif=True)
    session.add(eleve)
    session.commit()

    lien_premiere_connexion = creer_token_premiere_connexion(session, eleve)

    return {
        "id": eleve.id, "nom": eleve.nom, "prenom": eleve.prenom, "email": eleve.email,
        "lien_resalib": eleve.lien_resalib,
        "lien_resalib_visio": eleve.lien_resalib_visio,
        "lien_premiere_connexion": lien_premiere_connexion,
    }

@router.put("/eleves/{eleve_id}")
def modifier_eleve(
    eleve_id: int, nom: str = Form(...), prenom: str = Form(...), email: str = Form(...),
    lien_resalib: str = Form(None), lien_resalib_visio: str = Form(None),
    session: Session = Depends(obtenir_session),
):
    eleve = session.get(Eleve, eleve_id)
    if eleve is None:
        raise HTTPException(status_code=404, detail="ÃlÃ¨ve introuvable.")
    erreurs = _valider_champs_eleve(nom, prenom, email)
    if erreurs:
        raise HTTPException(status_code=400, detail=f"Champs requis manquants ou invalides : {', '.join(erreurs)}.")

    eleve.nom = nom.strip()
    eleve.prenom = prenom.strip()
    eleve.email = email.strip().lower()
    if lien_resalib is not None:
        eleve.lien_resalib = lien_resalib.strip() or None
    if lien_resalib_visio is not None:
        eleve.lien_resalib_visio = lien_resalib_visio.strip() or None
    session.commit()
    return {"id": eleve.id}

@router.post("/eleves/{eleve_id}/toggle-actif")
def toggle_actif_eleve(eleve_id: int, session: Session = Depends(obtenir_session)):
    eleve = session.get(Eleve, eleve_id)
    if eleve is None:
        raise HTTPException(status_code=404, detail="ÃlÃ¨ve introuvable.")
    eleve.actif = not eleve.actif
    session.commit()
    return {"id": eleve.id, "actif": eleve.actif}


@router.post("/eleves/{eleve_id}/toggle-test")
def toggle_test_eleve(eleve_id: int, session: Session = Depends(obtenir_session)):
    eleve = session.get(Eleve, eleve_id)
    if eleve is None:
        raise HTTPException(status_code=404, detail="ÃlÃ¨ve introuvable.")
    eleve.compte_test = not eleve.compte_test
    session.commit()
    return {"id": eleve.id, "compte_test": eleve.compte_test}

@router.delete("/eleves/{eleve_id}")
def supprimer_eleve(eleve_id: int, session: Session = Depends(obtenir_session)):
    eleve = session.get(Eleve, eleve_id)
    if eleve is None:
        raise HTTPException(status_code=404, detail="ÃlÃ¨ve introuvable.")
    session.delete(eleve)
    session.commit()
    return {"ok": True}

@router.get("/eleves/{eleve_id}")
def fiche_eleve(eleve_id: int, session: Session = Depends(obtenir_session)):
    eleve = session.get(Eleve, eleve_id)
    if eleve is None:
        raise HTTPException(status_code=404, detail="ÃlÃ¨ve introuvable.")
    acces_detail = []
    for acces in eleve.acces_formations:
        acces_detail.append({
            "formation_id": acces.formation_id,
            "formation_titre": acces.formation.titre,
            "niveau": acces.niveau,
            "nb_niveaux_formation": acces.formation.nb_niveaux,
            "progression": progression_pourcentage(session, eleve_id, acces.formation),
            "diplome_envoye": acces.diplome_envoye,
            "jours_cabinet_total": acces.formation.jours_pour_niveau(acces.niveau),
            "jours_cabinet_utilises": acces.jours_cabinet_utilises(),
            "jours_cabinet_restants": acces.jours_cabinet_restants(),
            "jours_visio_total": acces.formation.jours_visio_pour_niveau(acces.niveau),
            "jours_visio_utilises": acces.jours_visio_utilises(),
            "jours_visio_restants": acces.jours_visio_restants(),
            "historique_seances": [{"date": s.date_seance.isoformat(), "type": s.type_accompagnement, "statut": s.statut} for s in acces.seances_accompagnement],
        })
    return {
        "id": eleve.id,
        "nom": eleve.nom,
        "prenom": eleve.prenom,
        "email": eleve.email,
        "actif": eleve.actif,
        "mot_de_passe_actif": eleve.mot_de_passe_hash is not None,
        "compte_test": eleve.compte_test,
        "acces": acces_detail,
    }

# ---------- AccÃ¨s aux formations ----------

@router.post("/eleves/{eleve_id}/acces")
def donner_acces_formation(
    eleve_id: int, formation_id: int = Form(...), niveau: int = Form(1),
    session: Session = Depends(obtenir_session),
):
    eleve = session.get(Eleve, eleve_id)
    formation = session.get(Formation, formation_id)
    if eleve is None or formation is None:
        raise HTTPException(status_code=404, detail="ÃlÃ¨ve ou formation introuvable.")
    if False:  # formations inactives autorisees par admin
        raise HTTPException(status_code=400, detail="Cette formation est dÃ©sactivÃ©e, elle ne peut pas Ãªtre attribuÃ©e Ã  un Ã©lÃ¨ve.")

    niveau_final = niveau if formation.nb_niveaux > 1 else 1
    if niveau_final not in range(1, formation.nb_niveaux + 1):
        raise HTTPException(status_code=400, detail="Niveau invalide pour cette formation.")

    acces_existant = (
        session.query(AccesFormation)
        .filter_by(eleve_id=eleve_id, formation_id=formation_id)
        .first()
    )
    if acces_existant:
        acces_existant.niveau = niveau_final
    else:
        session.add(AccesFormation(eleve_id=eleve_id, formation_id=formation_id, niveau=niveau_final))
    session.commit()
    return {"ok": True}

@router.delete("/eleves/{eleve_id}/acces/{formation_id}")
def retirer_acces_formation(eleve_id: int, formation_id: int, session: Session = Depends(obtenir_session)):
    acces = (
        session.query(AccesFormation)
        .filter_by(eleve_id=eleve_id, formation_id=formation_id)
        .first()
    )
    if acces is None:
        raise HTTPException(status_code=404, detail="AccÃ¨s introuvable.")
    session.delete(acces)
    session.commit()
    return {"ok": True}

# ---------- RÃ©initialisation de l'avancement ----------

@router.post("/eleves/{eleve_id}/acces/{formation_id}/reinitialiser-avancement")
def reinitialiser_avancement(
    eleve_id: int, formation_id: int,
    session: Session = Depends(obtenir_session),
):
    """Supprime toutes les validations de chapitres d'un Ã©lÃ¨ve pour une formation donnÃ©e."""
    acces = (
        session.query(AccesFormation)
        .filter_by(eleve_id=eleve_id, formation_id=formation_id)
        .first()
    )
    if acces is None:
        raise HTTPException(status_code=404, detail="AccÃ¨s introuvable.")
    formation = session.get(Formation, formation_id)
    chapitre_ids = [c.id for m in formation.modules for c in m.chapitres]
    if chapitre_ids:
        session.query(ValidationChapitre).filter(
            ValidationChapitre.eleve_id == eleve_id,
            ValidationChapitre.chapitre_id.in_(chapitre_ids),
        ).delete(synchronize_session=False)
    session.commit()
    return {"ok": True}

# ---------- Accompagnement ----------

@router.post("/eleves/{eleve_id}/acces/{formation_id}/seance-accompagnement")
def enregistrer_seance_accompagnement(eleve_id: int, formation_id: int, type_accompagnement: str = Form("cabinet"), session: Session = Depends(obtenir_session)):
    acces = (
        session.query(AccesFormation)
        .filter_by(eleve_id=eleve_id, formation_id=formation_id)
        .first()
    )
    if acces is None:
        raise HTTPException(status_code=404, detail="AccÃ¨s introuvable.")
    if type_accompagnement == "visio":
        if acces.jours_visio_restants() <= 0:
            raise HTTPException(status_code=400, detail="Aucune sÃ©ance visio restante pour ce niveau.")
    else:
        if acces.jours_cabinet_restants() <= 0:
            raise HTTPException(status_code=400, detail="Aucune sÃ©ance cabinet restante pour ce niveau.")
    session.add(SeanceAccompagnement(acces_id=acces.id, type_accompagnement=type_accompagnement))
    session.commit()
    return {
        "ok": True,
        "jours_cabinet_restants": acces.jours_cabinet_restants(),
        "jours_visio_restants": acces.jours_visio_restants(),
    }

# ---------- DiplÃ´mes ----------

@router.get("/diplomes")
def lister_diplomes_en_attente(session: Session = Depends(obtenir_session)):
    """Tout Ã©lÃ¨ve ayant atteint 100% sur une formation, diplÃ´me pas encore marquÃ© envoyÃ©."""
    candidats = []
    for acces in session.query(AccesFormation).all():
        if acces.diplome_envoye:
            continue
        prog = progression_pourcentage(session, acces.eleve_id, acces.formation)
        if prog == 100.0:
            candidats.append({
                "eleve_id": acces.eleve_id,
                "eleve_nom": f"{acces.eleve.prenom} {acces.eleve.nom}",
                "formation_id": acces.formation_id,
                "formation_titre": acces.formation.titre,
            })
    return candidats

@router.post("/eleves/{eleve_id}/acces/{formation_id}/diplome-envoye")
def marquer_diplome_envoye(eleve_id: int, formation_id: int, session: Session = Depends(obtenir_session)):
    acces = (
        session.query(AccesFormation)
        .filter_by(eleve_id=eleve_id, formation_id=formation_id)
        .first()
    )
    if acces is None:
        raise HTTPException(status_code=404, detail="AccÃ¨s introuvable.")
    acces.diplome_envoye = True
    session.commit()
    return {"ok": True}

@router.get("/statistiques")
def lire_statistiques(session: Session = Depends(obtenir_session)):
    total_eleves = session.query(Eleve).count()
    total_formations = session.query(Formation).count()

    toutes_progressions = []
    for acces in session.query(AccesFormation).all():
        toutes_progressions.append(progression_pourcentage(session, acces.eleve_id, acces.formation))

    moyenne_globale = round(sum(toutes_progressions) / len(toutes_progressions), 0) if toutes_progressions else 0
    nb_parcours_termines = sum(1 for p in toutes_progressions if p == 100.0)

    lignes_par_formation = []
    for formation in session.query(Formation).all():
        progressions_f = [
            progression_pourcentage(session, a.eleve_id, formation)
            for a in formation.acces_eleves
        ]
        moyenne_f = round(sum(progressions_f) / len(progressions_f), 0) if progressions_f else 0
        lignes_par_formation.append({
            "titre": formation.titre,
            "nb_eleves": len(progressions_f),
            "moyenne": moyenne_f,
        })

    return {
        "total_eleves": total_eleves,
        "total_formations": total_formations,
        "moyenne_globale": moyenne_globale,
        "nb_parcours_termines": nb_parcours_termines,
        "par_formation": lignes_par_formation,
    }

# ---------- Statistiques de connexion ----------

@router.get("/statistiques/connexions")
def statistiques_connexions(session: Session = Depends(obtenir_session)):
    from ..models import AccesFormation, progression_pourcentage
    eleves = session.query(Eleve).all()
    resultats = []
    for e in eleves:
        acces_detail = []
        for acces in e.acces_formations:
            if acces.formation.actif:
                acces_detail.append({
                    "formation_titre": acces.formation.titre,
                    "progression": progression_pourcentage(session, e.id, acces.formation),
                })
        resultats.append({
            "id": e.id, "nom": e.nom, "prenom": e.prenom,
            "email": e.email, "actif": e.actif,
            "nb_connexions": e.nb_connexions or 0,
            "derniere_connexion": e.derniere_connexion.isoformat() if e.derniere_connexion else None,
            "formations": acces_detail,
        })
    resultats.sort(key=lambda x: x["nb_connexions"], reverse=True)
    return resultats

# ---------------------------------------------------------------------------
# Coaching -- gestion des sÃ©ances d'accompagnement
# ---------------------------------------------------------------------------

@router.post("/eleves/{eleve_id}/coaching/envoyer")
def coaching_envoyer_lien(
    eleve_id: int,
    lien_resalib: str = Form(...),
    session: Session = Depends(obtenir_session),
):
    """Admin envoie manuellement un lien coaching Ã  la cliente (sÃ©ances 2, 3â¦)."""
    acces = session.query(AccesFormation).filter_by(eleve_id=eleve_id).first()
    if acces is None:
        raise HTTPException(status_code=404, detail="AccÃ¨s formation introuvable.")
    eleve = session.get(Eleve, eleve_id)
    if eleve is None:
        raise HTTPException(status_code=404, detail="ÃlÃ¨ve introuvable.")

    seance = SeanceAccompagnement(
        acces_id=acces.id,
        lien_resalib=lien_resalib,
        type_envoi="manuel",
        statut="en_attente",
    )
    session.add(seance)
    session.commit()
    session.refresh(seance)

    email_coaching_rdv(
        destinataire=eleve.email,
        prenom=eleve.prenom,
        lien_resalib=lien_resalib,
        titre_formation=acces.formation.titre,
    )
    return {"ok": True, "seance_id": seance.id}

@router.post("/eleves/{eleve_id}/seances/{seance_id}/realiser")
def coaching_marquer_realise(
    eleve_id: int,
    seance_id: int,
    session: Session = Depends(obtenir_session),
):
    """Admin marque une sÃ©ance comme rÃ©alisÃ©e â le compteur avance d'une unitÃ©."""
    seance = session.get(SeanceAccompagnement, seance_id)
    if seance is None or seance.acces.eleve_id != eleve_id:
        raise HTTPException(status_code=404, detail="SÃ©ance introuvable.")
    seance.statut = "realise"
    seance.date_realise = datetime.utcnow()
    session.commit()
    return {"ok": True}

@router.get("/coaching/global")
def coaching_global(session: Session = Depends(obtenir_session)):
    """Toutes les sÃ©ances coaching, toutes Ã©lÃ¨ves confondues â pour la page admin globale."""
    from sqlalchemy.orm import joinedload
    seances_db = (
        session.query(SeanceAccompagnement)
        .options(
            joinedload(SeanceAccompagnement.acces).joinedload(AccesFormation.eleve),
            joinedload(SeanceAccompagnement.acces).joinedload(AccesFormation.formation),
        )
        .order_by(SeanceAccompagnement.date_seance.desc())
        .all()
    )
    seances = []
    for s in seances_db:
        acces = s.acces
        eleve = acces.eleve
        formation = acces.formation
        seances.append({
            "id": s.id,
            "eleve_id": eleve.id,
            "eleve_nom": f"{eleve.prenom} {eleve.nom}",
            "eleve_email": eleve.email,
            "formation": formation.titre,
            "date_seance": s.date_seance.isoformat(),
            "type_envoi": s.type_envoi or "manuel",
            "statut": s.statut,
            "date_realise": s.date_realise.isoformat() if s.date_realise else None,
            "lien_resalib": s.lien_resalib or "",
        })
    en_attente = [s for s in seances if s["statut"] == "en_attente"]
    realises = [s for s in seances if s["statut"] == "realise"]
    return {"en_attente": en_attente, "realises": realises, "total": len(seances)}


@router.get("/eleves/{eleve_id}/coaching/historique")
def coaching_historique(
    eleve_id: int,
    session: Session = Depends(obtenir_session),
):
    """Retourne toutes les sÃ©ances coaching de cet Ã©lÃ¨ve avec leur statut."""
    acces_list = session.query(AccesFormation).filter_by(eleve_id=eleve_id).all()
    seances = []
    for acces in acces_list:
        for s in acces.seances_accompagnement:
            seances.append({
                "id": s.id,
                "formation": acces.formation.titre,
                "date_seance": s.date_seance.isoformat(),
                "lien_resalib": s.lien_resalib,
                "type_envoi": s.type_envoi,
                "statut": s.statut,
                "date_realise": s.date_realise.isoformat() if s.date_realise else None,
            })
    seances.sort(key=lambda x: x["date_seance"], reverse=True)
    return {"seances": seances}
