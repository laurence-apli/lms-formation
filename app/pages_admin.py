"""
Routes qui servent les vraies pages HTML de l'administration, en réutilisant
les routes API déjà existantes (formations.py, eleves.py) comme source de
données via JavaScript côté client -- même principe que pages.py pour l'élève.
"""
from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .database import obtenir_session
from .models import Administrateur, Formation
from .routes.auth import admin_connecte

router = APIRouter(prefix="/admin/page")
templates = Jinja2Templates(directory="app/templates")


def _profil_admin(admin: Administrateur) -> dict:
    return {
        "nom": admin.nom, "prenom": admin.prenom, "email": admin.email,
        "telephone": admin.telephone, "photo_url": admin.photo_url,
        "logo_url": admin.logo_url, "lien_github": admin.lien_github,
    }


@router.get("/formations", response_class=HTMLResponse)
def page_liste_formations(request: Request, admin: Administrateur = Depends(admin_connecte)):
    return templates.TemplateResponse(
        request, "admin/formations_liste.html",
        {"profil": _profil_admin(admin), "page_active": "formations"},
    )


@router.get("/formations/{formation_id}", response_class=HTMLResponse)
def page_detail_formation(
    request: Request, formation_id: int, admin: Administrateur = Depends(admin_connecte),
    session: Session = Depends(obtenir_session),
):
    formation = session.get(Formation, formation_id)
    if formation is None:
        raise HTTPException(status_code=404, detail="Formation introuvable.")
    return templates.TemplateResponse(
        request, "admin/formation_detail.html",
        {"profil": _profil_admin(admin), "page_active": "formations", "formation": formation},
    )


@router.get("/eleves", response_class=HTMLResponse)
def page_liste_eleves(request: Request, admin: Administrateur = Depends(admin_connecte)):
    return templates.TemplateResponse(
        request, "admin/eleves_liste.html",
        {"profil": _profil_admin(admin), "page_active": "eleves"},
    )


@router.get("/eleves/{eleve_id}", response_class=HTMLResponse)
def page_fiche_eleve(request: Request, eleve_id: int, admin: Administrateur = Depends(admin_connecte)):
    return templates.TemplateResponse(
        request, "admin/eleve_fiche.html",
        {"profil": _profil_admin(admin), "page_active": "eleves", "eleve_id": eleve_id},
    )


@router.get("/diplomes", response_class=HTMLResponse)
def page_diplomes(request: Request, admin: Administrateur = Depends(admin_connecte)):
    return templates.TemplateResponse(
        request, "admin/diplomes.html",
        {"profil": _profil_admin(admin), "page_active": "diplomes"},
    )


@router.get("/profil", response_class=HTMLResponse)
def page_profil(request: Request, admin: Administrateur = Depends(admin_connecte)):
    return templates.TemplateResponse(
        request, "admin/profil.html",
        {"profil": _profil_admin(admin), "page_active": "profil"},
    )
