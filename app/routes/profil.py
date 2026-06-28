"""
Route de gestion du profil de l'administratrice -- nom, contact, photo, logo,
lien vers le dépôt technique (GitHub). Réservée à l'administrateur connecté.
"""
from fastapi import APIRouter, Depends, Form
from sqlalchemy.orm import Session

from ..database import obtenir_session
from ..models import Administrateur
from .auth import admin_connecte

router = APIRouter(prefix="/admin", dependencies=[Depends(admin_connecte)])


@router.get("/profil")
def lire_profil(admin: Administrateur = Depends(admin_connecte)):
    return {
        "nom": admin.nom, "prenom": admin.prenom, "email": admin.email,
        "telephone": admin.telephone, "photo_url": admin.photo_url,
        "logo_url": admin.logo_url, "lien_github": admin.lien_github,
    }


@router.put("/profil")
def modifier_profil(
    nom: str = Form(...), prenom: str = Form(...), email: str = Form(""),
    telephone: str = Form(""), lien_github: str = Form(""),
    admin: Administrateur = Depends(admin_connecte), session: Session = Depends(obtenir_session),
):
    admin.nom = nom.strip()
    admin.prenom = prenom.strip()
    admin.email = email.strip().lower() or admin.email
    admin.telephone = telephone.strip()
    admin.lien_github = lien_github.strip()
    session.commit()
    return {"ok": True}


@router.put("/profil/photo")
def modifier_photo(url: str = Form(...), admin: Administrateur = Depends(admin_connecte), session: Session = Depends(obtenir_session)):
    """Reçoit une URL de photo déjà hébergée ailleurs (ou une data URI courte
    pour un aperçu local) -- le vrai stockage de fichiers (upload + hébergement
    durable) viendra avec l'intégration finale, pas indispensable pour l'usage
    immédiat de l'administration."""
    admin.photo_url = url
    session.commit()
    return {"ok": True}


@router.put("/profil/logo")
def modifier_logo(url: str = Form(...), admin: Administrateur = Depends(admin_connecte), session: Session = Depends(obtenir_session)):
    admin.logo_url = url
    session.commit()
    return {"ok": True}
