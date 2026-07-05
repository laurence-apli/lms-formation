"""
Routes d'authentification -- élèves ET administrateur.

Principes de sécurité appliqués :
- Les mots de passe ne sont JAMAIS stockés en clair (hachage bcrypt, voir models.py)
- Les liens de première connexion / réinitialisation utilisent des tokens
  aléatoires à usage unique et à durée limitée (jamais l'identifiant interne)
- On ne révèle jamais si un e-mail existe ou non dans la base lors d'une demande
  de réinitialisation (sinon on permettrait de "deviner" qui est élève chez Laurence)
- Les sessions sont gérées par cookie signé (Starlette SessionMiddleware),
  jamais par un identifiant transmis en clair dans l'URL
"""
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, Request, HTTPException, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ..database import obtenir_session
from ..models import (
    Eleve, Administrateur, TokenAuthEleve, TokenAuthAdmin,
    generer_token_reinitialisation,
)
from ..emails import email_reinitialisation_mot_de_passe
from ..config import URL_PLATEFORME, DUREE_VALIDITE_TOKEN_HEURES

router = APIRouter()


# ---------- Création de tokens (appelée par l'admin quand elle crée un élève) ----------

def creer_token_premiere_connexion(session: Session, eleve: Eleve) -> str:
    token_str = generer_token_reinitialisation()
    token = TokenAuthEleve(
        eleve_id=eleve.id,
        token=token_str,
        type_token="premiere_connexion",
        expire_le=datetime.utcnow() + timedelta(hours=DUREE_VALIDITE_TOKEN_HEURES),
    )
    session.add(token)
    session.commit()

    lien = f"{URL_PLATEFORME}/eleve/definir-mot-de-passe/{token_str}"
    return lien


# ---------- Connexion élève ----------

@router.post("/eleve/connexion")
def connexion_eleve(request: Request, email: str = Form(...), mot_de_passe: str = Form(...),
                     session: Session = Depends(obtenir_session)):
    eleve = session.query(Eleve).filter_by(email=email.strip().lower()).first()
    erreur_generique = "E-mail ou mot de passe incorrect."

    if eleve is None or not eleve.verifier_mot_de_passe(mot_de_passe):
        raise HTTPException(status_code=401, detail=erreur_generique)

    if not eleve.actif:
        raise HTTPException(status_code=403, detail="Votre compte est actuellement inactif. Merci de contacter votre formatrice.")

    # NOUVEAU : mise à jour des statistiques de connexion
    eleve.derniere_connexion = datetime.utcnow()
    eleve.nb_connexions = (eleve.nb_connexions or 0) + 1
    session.commit()

    request.session["eleve_id"] = eleve.id
    return RedirectResponse(url="/eleve/tableau-de-bord", status_code=303)


@router.post("/eleve/definir-mot-de-passe/{token}")
def definir_mot_de_passe(token: str, nouveau_mot_de_passe: str = Form(...),
                          session: Session = Depends(obtenir_session)):
    token_obj = session.query(TokenAuthEleve).filter_by(token=token).first()
    if token_obj is None or not token_obj.est_valide():
        raise HTTPException(status_code=400, detail="Ce lien n'est plus valide. Demandez un nouveau lien de connexion.")

    if len(nouveau_mot_de_passe) < 8:
        raise HTTPException(status_code=400, detail="Le mot de passe doit contenir au moins 8 caractères.")

    eleve = session.get(Eleve, token_obj.eleve_id)
    eleve.definir_mot_de_passe(nouveau_mot_de_passe)
    token_obj.utilise_le = datetime.utcnow()
    session.commit()
    return {"ok": True}

@router.post("/eleve/mot-de-passe-oublie")
def demander_reinitialisation_eleve(email: str = Form(...), session: Session = Depends(obtenir_session)):
    eleve = session.query(Eleve).filter_by(email=email.strip().lower()).first()
    if eleve is not None:
        token_str = generer_token_reinitialisation()
        token = TokenAuthEleve(
            eleve_id=eleve.id, token=token_str, type_token="reinitialisation",
            expire_le=datetime.utcnow() + timedelta(hours=DUREE_VALIDITE_TOKEN_HEURES),
        )
        session.add(token)
        session.commit()
        lien = f"{URL_PLATEFORME}/eleve/definir-mot-de-passe/{token_str}"
        email_reinitialisation_mot_de_passe(eleve.email, eleve.prenom, lien)

    return {"message": "Si cette adresse existe dans notre système, un e-mail de réinitialisation vient d'être envoyé."}


@router.post("/eleve/deconnexion")
def deconnexion_eleve(request: Request):
    request.session.pop("eleve_id", None)
    return RedirectResponse(url="/eleve/connexion", status_code=303)


def eleve_connecte(request: Request, session: Session = Depends(obtenir_session)) -> Eleve:
    eleve_id = request.session.get("eleve_id")
    if eleve_id is None:
        raise HTTPException(status_code=401, detail="Connexion requise.")
    eleve = session.get(Eleve, eleve_id)
    if eleve is None or not eleve.actif:
        request.session.pop("eleve_id", None)
        raise HTTPException(status_code=401, detail="Connexion requise.")
    return eleve


# ---------- Connexion administrateur ----------

@router.post("/admin/connexion")
def connexion_admin(request: Request, email: str = Form(...), mot_de_passe: str = Form(...),
                     session: Session = Depends(obtenir_session)):
    admin = session.query(Administrateur).filter_by(email=email.strip().lower()).first()
    erreur_generique = "E-mail ou mot de passe incorrect."

    if admin is None or not admin.verifier_mot_de_passe(mot_de_passe):
        raise HTTPException(status_code=401, detail=erreur_generique)

    request.session["admin_id"] = admin.id
    return RedirectResponse(url="/admin/page/formations", status_code=303)


@router.post("/admin/mot-de-passe-oublie")
def demander_reinitialisation_admin(email: str = Form(...), session: Session = Depends(obtenir_session)):
    admin = session.query(Administrateur).filter_by(email=email.strip().lower()).first()
    if admin is not None:
        token_str = generer_token_reinitialisation()
        token = TokenAuthAdmin(
            administrateur_id=admin.id, token=token_str, type_token="reinitialisation",
            expire_le=datetime.utcnow() + timedelta(hours=DUREE_VALIDITE_TOKEN_HEURES),
        )
        session.add(token)
        session.commit()
        lien = f"{URL_PLATEFORME}/admin/definir-mot-de-passe/{token_str}"
        email_reinitialisation_mot_de_passe(admin.email, admin.prenom, lien)

    return {"message": "Si cette adresse existe dans notre système, un e-mail de réinitialisation vient d'être envoyé."}


@router.post("/admin/definir-mot-de-passe/{token}")
def definir_mot_de_passe_admin(token: str, nouveau_mot_de_passe: str = Form(...),
                                session: Session = Depends(obtenir_session)):
    token_obj = session.query(TokenAuthAdmin).filter_by(token=token).first()
    if token_obj is None or not token_obj.est_valide():
        raise HTTPException(status_code=400, detail="Ce lien n'est plus valide. Demandez un nouveau lien.")

    if len(nouveau_mot_de_passe) < 8:
        raise HTTPException(status_code=400, detail="Le mot de passe doit contenir au moins 8 caractères.")

    admin = session.get(Administrateur, token_obj.administrateur_id)
    admin.definir_mot_de_passe(nouveau_mot_de_passe)
    token_obj.utilise_le = datetime.utcnow()
    session.commit()
    return RedirectResponse(url="/admin/connexion", status_code=303)


@router.post("/admin/deconnexion")
def deconnexion_admin(request: Request):
    request.session.pop("admin_id", None)
    return RedirectResponse(url="/admin/connexion", status_code=303)


def admin_connecte(request: Request, session: Session = Depends(obtenir_session)) -> Administrateur:
    admin_id = request.session.get("admin_id")
    if admin_id is None:
        raise HTTPException(status_code=401, detail="Connexion requise.")
    admin = session.get(Administrateur, admin_id)
    if admin is None:
        request.session.pop("admin_id", None)
        raise HTTPException(status_code=401, detail="Connexion requise.")
    return admin
