"""
Routes qui servent les vraies pages HTML visuelles, en réutilisant les routes
API (JSON) déjà existantes comme source de données via JavaScript côté client.

Séparation volontaire : les routes dans espace_eleve.py / eleves.py /
formations.py restent de pures API (testées indépendamment), ces routes-ci ne
font que choisir QUELLE page HTML afficher et avec QUELLES données de départ.
"""
from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .database import obtenir_session
from .models import Eleve, Formation, Administrateur, TokenAuthEleve, TokenAuthAdmin, AccesFormation, progression_pourcentage
from .routes.auth import eleve_connecte
from .config import URL_SITE_VITRINE

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _profil_pour_affichage(session: Session) -> dict:
    """Le profil de l'administratrice, affiché dans la topbar élève (logo, nom)
    et dans la colonne de gauche de l'écran de formation (photo). S'il n'existe
    pas encore de compte admin (cas impossible en pratique puisqu'il faut un
    admin pour créer des élèves, mais on reste défensif), on renvoie des
    valeurs neutres plutôt que de planter la page."""
    admin = session.query(Administrateur).first()
    if admin is None:
        return {"nom": "", "prenom": "", "email": "", "logo_url": None, "photo_url": None}
    return {
        "nom": admin.nom, "prenom": admin.prenom, "email": admin.email,
        "logo_url": admin.logo_url, "photo_url": admin.photo_url,
    }


@router.get("/eleve/connexion", response_class=HTMLResponse)
def page_connexion(request: Request):
    return templates.TemplateResponse(request, "eleve/connexion.html", {})


@router.get("/admin/connexion", response_class=HTMLResponse)
def page_connexion_admin(request: Request):
    return templates.TemplateResponse(request, "admin/connexion.html", {})


@router.get("/admin/definir-mot-de-passe/{token}", response_class=HTMLResponse)
def page_definir_mot_de_passe_admin(request: Request, token: str, session: Session = Depends(obtenir_session)):
    token_obj = session.query(TokenAuthAdmin).filter_by(token=token).first()
    token_valide = token_obj is not None and token_obj.est_valide()
    return templates.TemplateResponse(
        request, "admin/definir_mot_de_passe.html", {"token_valide": token_valide},
    )


@router.get("/eleve/definir-mot-de-passe/{token}", response_class=HTMLResponse)
def page_definir_mot_de_passe(request: Request, token: str, session: Session = Depends(obtenir_session)):
    token_obj = session.query(TokenAuthEleve).filter_by(token=token).first()
    token_valide = token_obj is not None and token_obj.est_valide()
    return templates.TemplateResponse(
        request, "eleve/definir_mot_de_passe.html", {"token_valide": token_valide, "token": token},
    )


@router.get("/eleve/tableau-de-bord", response_class=HTMLResponse)
def page_tableau_de_bord(
    request: Request, eleve: Eleve = Depends(eleve_connecte), session: Session = Depends(obtenir_session),
):
    formations_acquises = []
    for acces in eleve.acces_formations:
        formation = acces.formation
        if not formation.actif:
            continue
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
    return templates.TemplateResponse(
        request, "eleve/tableau_de_bord.html",
        {
            "eleve": eleve,
            "formations_acquises": formations_acquises,
            "formations_disponibles": formations_disponibles,
            "profil": _profil_pour_affichage(session),
            "url_site_vitrine": URL_SITE_VITRINE,
        },
    )


@router.get("/eleve/voir-formation/{formation_id}", response_class=HTMLResponse)
def page_formation(
    request: Request, formation_id: int, eleve: Eleve = Depends(eleve_connecte),
    session: Session = Depends(obtenir_session),
):
    formation = session.get(Formation, formation_id)
    if formation is None:
        raise HTTPException(status_code=404, detail="Formation introuvable.")
    acces = (
        session.query(AccesFormation)
        .filter_by(eleve_id=eleve.id, formation_id=formation_id)
        .first()
    )
    if acces is None:
        raise HTTPException(status_code=403, detail="Vous n'avez pas accès à cette formation.")
    if not formation.actif:
        raise HTTPException(status_code=403, detail="Cette formation n'est actuellement pas disponible.")
    return templates.TemplateResponse(
        request, "eleve/formation.html",
        {"eleve": eleve, "formation": formation, "profil": _profil_pour_affichage(session), "url_site_vitrine": URL_SITE_VITRINE},
    )
