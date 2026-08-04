"""
Routes de gestion des élèves -- réservées à l'administrateur connecté.
Couvre : fiche élève centrale, accès aux formations avec niveau, jours
d'accompagnement, diplômes, et la création de compte avec envoi d'e-mail
automatique de première connexion.
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
        erreurs.append("le prénom")
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
        raise HTTPException(status_code=400, detail="Un élève existe déjà avec cet e-mail.")

    eleve = Eleve(nom=nom.strip(), prenom=prenom.strip(), email=email_normalise, actif=True)
    session.add(eleve)
    session.commit()

    lien_premiere_connexion = creer_token_premiere_connexion(session, eleve)

    return {
        "id": eleve.id, "nom": eleve.nom, "prenom": eleve.prenom, "email": eleve.email,
        "lien_premiere_connexion": lien_premiere_connexion,
    }

@router.put("/eleves/{eleve_id}")
def modifier_eleve(
    eleve_id: int, nom: str = Form(...), prenom: str = Form(...), email: str = Form(...),
    session: Session = Depends(obtenir_session),
):
    eleve = session.get(Eleve, eleve_id)
    if eleve is None:
        raise HTTPException(status_code=404, detail="Élève introuvable.")
    erreurs = _valider_champs_eleve(nom, prenom, email)
    if erreurs:
        raise HTTPException(status_code=400, detail=f"Champs requis manquants ou invalides : {', '.join(erreurs)}.")

    eleve.nom = nom.strip()
    eleve.prenom = prenom.strip()
    eleve.email = email.strip().lower()
    session.commit()
    return {"id": eleve.id}

@router.post("/eleves/{eleve_id}/toggle-actif")
def toggle_actif_eleve(eleve_id: int, session: Session = Depends(obtenir_session)):
    eleve = session.get(Eleve, eleve_id)
    if eleve is None:
        raise HTTPException(status_code=404, detail="Élève introuvable.")
    eleve.actif = not eleve.actif
    session.commit()
    return {"id": eleve.id, "actif": eleve.actif}


@router.post("/eleves/{eleve_id}/toggle-test")
def toggle_test_eleve(eleve_id: int, session: Session = Depends(obtenir_session)):
    eleve = session.get(Eleve, eleve_id)
    if eleve is None:
        raise HTTPException(status_code=404, detail="Élève introuvable.")
    eleve.compte_test = not eleve.compte_test
    session.commit()
    return {"id": eleve.id, "compte_test": eleve.compte_test}

@router.delete("/eleves/{eleve_id}")
def supprimer_eleve(eleve_id: int, session: Session = Depends(obtenir_session)):
    eleve = session.get(Eleve, eleve_id)
    if eleve is None:
        raise HTTPException(status_code=404, detail="Élève introuvable.")
    session.delete(eleve)
    session.commit()
    return {"ok": True}

@router.get("/eleves/{eleve_id}")
def fiche_eleve(eleve_id: int, session: Session = Depends(obtenir_session)):
    eleve = session.get(Eleve, eleve_id)
    if eleve is None:
        raise HTTPException(status_code=404, detail="Élève introuvable.")
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

# ---------- Accès aux formations ----------

@router.post("/eleves/{eleve_id}/acces")
def donner_acces_formation(
    eleve_id: int, formation_id: int = Form(...), niveau: int = Form(1),
    session: Session = Depends(obtenir_session),
):
    eleve = session.get(Eleve, eleve_id)
    formation = session.get(Formation, formation_id)
    if eleve is None or formation is None:
        raise HTTPException(status_code=404, detail="Élève ou formation introuvable.")
    if False:  # formations inactives autorisees par admin
        raise HTTPException(status_code=400, detail="Cette formation est désactivée, elle ne peut pas être attribuée à un élève.")

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
        raise HTTPException(status_code=404, detail="Accès introuvable.")
    session.delete(acces)
    session.commit()
    return {"ok": True}

# ---------- Réinitialisation de l'avancement ----------

@router.post("/eleves/{eleve_id}/acces/{formation_id}/reinitialiser-avancement")
def reinitialiser_avancement(
    eleve_id: int, formation_id: int,
    session: Session = Depends(obtenir_session),
):
    """Supprime toutes les validations de chapitres d'un élève pour une formation donnée."""
    acces = (
        session.query(AccesFormation)
        .filter_by(eleve_id=eleve_id, formation_id=formation_id)
        .first()
    )
    if acces is None:
        raise HTTPException(status_code=404, detail="Accès introuvable.")
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
        raise HTTPException(status_code=404, detail="Accès introuvable.")
    if type_accompagnement == "visio":
        if acces.jours_visio_restants() <= 0:
            raise HTTPException(status_code=400, detail="Aucune séance visio restante pour ce niveau.")
    else:
        if acces.jours_cabinet_restants() <= 0:
            raise HTTPException(status_code=400, detail="Aucune séance cabinet restante pour ce niveau.")
    session.add(SeanceAccompagnement(acces_id=acces.id, type_accompagnement=type_accompagnement))
    session.commit()
    return {
        "ok": True,
        "jours_cabinet_restants": acces.jours_cabinet_restants(),
        "jours_visio_restants": acces.jours_visio_restants(),
    }

# ---------- Diplômes ----------

@router.get("/diplomes")
def lister_diplomes_en_attente(session: Session = Depends(obtenir_session)):
    """Tout élève ayant atteint 100% sur une formation, diplôme pas encore marqué envoyé."""
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
        raise HTTPException(status_code=404, detail="Accès introuvable.")
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
# Coaching -- gestion des séances d'accompagnement
# ---------------------------------------------------------------------------

@router.post("/eleves/{eleve_id}/coaching/envoyer")
def coaching_envoyer_lien(
    eleve_id: int,
    lien_resalib: str = Form(...),
    session: Session = Depends(obtenir_session),
):
    """Admin envoie manuellement un lien coaching à la cliente (séances 2, 3…)."""
    acces = session.query(AccesFormation).filter_by(eleve_id=eleve_id).first()
    if acces is None:
        raise HTTPException(status_code=404, detail="Accès formation introuvable.")
    eleve = session.get(Eleve, eleve_id)
    if eleve is None:
        raise HTTPException(status_code=404, detail="Élève introuvable.")

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
    """Admin marque une séance comme réalisée — le compteur avance d'une unité."""
    seance = session.get(SeanceAccompagnement, seance_id)
    if seance is None or seance.acces.eleve_id != eleve_id:
        raise HTTPException(status_code=404, detail="Séance introuvable.")
    seance.statut = "realise"
    seance.date_realise = datetime.utcnow()
    session.commit()
    return {"ok": True}

@router.get("/coaching/global")
def coaching_global(session: Session = Depends(obtenir_session)):
    """Toutes les séances coaching, toutes élèves confondues — pour la page admin globale."""
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
    """Retourne toutes les séances coaching de cet élève avec leur statut."""
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
