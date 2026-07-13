"""
Routes API pour le Cercle de Femmes.
- /admin/cercle-femmes (protégée) : lecture + modification depuis l'admin
- /public/cercle-femmes (ouverte, lecture seule) : consommée par le site vitrine
"""
from fastapi import APIRouter, Depends, Form
from sqlalchemy.orm import Session

from ..database import obtenir_session
from ..models import Administrateur, CercleFemmes, obtenir_ou_creer_cercle_femmes
from .auth import admin_connecte

router = APIRouter()


@router.get("/admin/cercle-femmes")
def lire_cercle_femmes_admin(
    session: Session = Depends(obtenir_session),
    admin: Administrateur = Depends(admin_connecte),
):
    cercle = obtenir_ou_creer_cercle_femmes(session)
    return {
        "titre": cercle.titre,
        "date_evenement": cercle.date_evenement,
        "lieu": cercle.lieu,
        "description_html": cercle.description_html,
        "photo_url": cercle.photo_url,
        "publie": cercle.publie,
    }


@router.post("/admin/cercle-femmes")
def modifier_cercle_femmes(
    titre: str = Form("Cercle de Femmes"),
    date_evenement: str = Form(""),
    lieu: str = Form(""),
    description_html: str = Form(""),
    photo_url: str = Form(""),
    publie: bool = Form(False),
    session: Session = Depends(obtenir_session),
    admin: Administrateur = Depends(admin_connecte),
):
    cercle = obtenir_ou_creer_cercle_femmes(session)
    cercle.titre = titre
    cercle.date_evenement = date_evenement
    cercle.lieu = lieu
    cercle.description_html = description_html
    if photo_url:
        cercle.photo_url = photo_url
    cercle.publie = publie
    session.commit()
    return {"ok": True}


@router.get("/public/cercle-femmes")
def lire_cercle_femmes_public(session: Session = Depends(obtenir_session)):
    """Route SANS authentification -- c'est celle que le site vitrine appelle
    en JavaScript. Ne renvoie jamais rien de sensible."""
    cercle = obtenir_ou_creer_cercle_femmes(session)
    return {
        "titre": cercle.titre,
        "date_evenement": cercle.date_evenement,
        "lieu": cercle.lieu,
        "description_html": cercle.description_html,
        "photo_url": cercle.photo_url,
        "publie": cercle.publie,
    }
