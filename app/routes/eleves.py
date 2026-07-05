"""
Routes de gestion des élèves -- réservées à l'administrateur connecté.
Couvre : fiche élève centrale, accès aux formations avec niveau, jours
d'accompagnement, diplômes, et la création de compte avec envoi d'e-mail
automatique de première connexion.
"""
import re
from fastapi import APIRouter, Depends, Form, HTTPException
from sqlalchemy.orm import Session

from ..database import obtenir_session
from ..models import (
    Eleve, Formation, AccesFormation, SeanceAccompagnement,
    progression_pourcentage,
)
from .auth import admin_connecte, creer_token_premiere_connexion

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

    # Crée le lien de première connexion, SANS envoi automatique -- Laurence
    # garde la maîtrise complète : c'est elle qui ouvre et valide le mailto
    # généré côté interface avant que quoi que ce soit ne soit envoyé.
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
            "jours_accompagnement_restants": acces.jours_accompagnement_restants(),
            "jours_accompagnement_total": acces.formation.jours_pour_niveau(acces.niveau),
            "historique_seances": [s.date_seance.isoformat() for s in acces.seances_accompagnement],
        })
   return {
        "id": eleve.id, "nom": eleve.nom, "prenom": eleve.prenom,
       "email": eleve.email, "actif": eleve.actif,
            "mot_de_passe_actif": eleve.mot_de_passe_hash is not None,
            "acces": acces_detail,
        "mot_de_passe_actif": eleve.mot_de_passe_hash is not None,
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
    if not formation.actif:
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


# ---------- Accompagnement ----------

@router.post("/eleves/{eleve_id}/acces/{formation_id}/seance-accompagnement")
def enregistrer_seance_accompagnement(eleve_id: int, formation_id: int, session: Session = Depends(obtenir_session)):
    acces = (
        session.query(AccesFormation)
        .filter_by(eleve_id=eleve_id, formation_id=formation_id)
        .first()
    )
    if acces is None:
        raise HTTPException(status_code=404, detail="Accès introuvable.")
    if acces.jours_accompagnement_restants() <= 0:
        raise HTTPException(status_code=400, detail="Aucune séance d'accompagnement restante pour ce niveau.")
    session.add(SeanceAccompagnement(acces_id=acces.id))
    session.commit()
    return {"ok": True, "jours_restants": acces.jours_accompagnement_restants()}


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

# ---------- NOUVEAU : statistiques de connexion ----------

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
