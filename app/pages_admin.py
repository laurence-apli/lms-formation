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
from .models import Administrateur, Formation, Offre
from .routes.auth import admin_connecte
from .config import URL_SITE_VITRINE

router = APIRouter(prefix="/admin/page")
templates = Jinja2Templates(directory="app/templates")


def _profil_admin(admin: Administrateur) -> dict:
    return {
        "nom": admin.nom, "prenom": admin.prenom, "email": admin.email,
        "telephone": admin.telephone, "photo_url": admin.photo_url,
        "logo_url": admin.logo_url, "lien_github": admin.lien_github,
    }


def _rendre(request: Request, nom_template: str, contexte: dict):
    """Petite fonction centrale qui ajoute automatiquement url_site_vitrine
    à toutes les pages admin -- évite d'avoir à le répéter (et risquer de
    l'oublier) sur chacune des routes ci-dessous."""
    contexte = {**contexte, "url_site_vitrine": URL_SITE_VITRINE}
    return templates.TemplateResponse(request, nom_template, contexte)


@router.get("/formations", response_class=HTMLResponse)
def page_liste_formations(request: Request, admin: Administrateur = Depends(admin_connecte)):
    return _rendre(
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
    return _rendre(
        request, "admin/formation_detail.html",
        {"profil": _profil_admin(admin), "page_active": "formations", "formation": formation},
    )


@router.get("/eleves", response_class=HTMLResponse)
def page_liste_eleves(request: Request, admin: Administrateur = Depends(admin_connecte)):
    return _rendre(
        request, "admin/eleves_liste.html",
        {"profil": _profil_admin(admin), "page_active": "eleves"},
    )


@router.get("/eleves/{eleve_id}", response_class=HTMLResponse)
def page_fiche_eleve(request: Request, eleve_id: int, admin: Administrateur = Depends(admin_connecte)):
    return _rendre(
        request, "admin/eleve_fiche.html",
        {"profil": _profil_admin(admin), "page_active": "eleves", "eleve_id": eleve_id},
    )


@router.get("/diplomes", response_class=HTMLResponse)
def page_diplomes(request: Request, admin: Administrateur = Depends(admin_connecte)):
    return _rendre(
        request, "admin/diplomes.html",
        {"profil": _profil_admin(admin), "page_active": "diplomes"},
    )


@router.get("/statistiques", response_class=HTMLResponse)
def page_statistiques(request: Request, admin: Administrateur = Depends(admin_connecte)):
    return _rendre(
        request, "admin/statistiques.html",
        {"profil": _profil_admin(admin), "page_active": "statistiques"},
    )


@router.get("/profil", response_class=HTMLResponse)
def page_profil(request: Request, admin: Administrateur = Depends(admin_connecte)):
    return _rendre(
        request, "admin/profil.html",
        {"profil": _profil_admin(admin), "page_active": "profil"},
    )

@router.get("/cercle-femmes", response_class=HTMLResponse)
def page_cercle_femmes(request: Request, admin: Administrateur = Depends(admin_connecte)):
    return _rendre(
        request, "admin/cercle_femmes.html",
        {"profil": _profil_admin(admin), "page_active": "cercle_femmes"},
    )

@router.get("/catalogue-tarifs", response_class=HTMLResponse)
def page_catalogue_tarifs(request: Request, admin: Administrateur = Depends(admin_connecte)):
    return _rendre(
        request, "admin/catalogue_tarifs.html",
        {"profil": _profil_admin(admin), "page_active": "catalogue_tarifs"},
    )


@router.get("/codes-promo", response_class=HTMLResponse)
def page_codes_promo(request: Request, admin: Administrateur = Depends(admin_connecte)):
    return _rendre(
        request, "admin/codes_promo.html",
        {"profil": _profil_admin(admin), "page_active": "codes_promo"},
    )


@router.get("/coaching", response_class=HTMLResponse)
def page_coaching(request: Request, admin: Administrateur = Depends(admin_connecte)):
    return _rendre(
        request, "admin/coaching.html",
        {"profil": _profil_admin(admin), "page_active": "coaching"},
    )


@router.get("/offres", response_class=HTMLResponse)
def page_offres(
    request: Request,
    admin: Administrateur = Depends(admin_connecte),
    session: Session = Depends(obtenir_session),
):
    formations = session.query(Formation).filter_by(actif=True).order_by(Formation.titre).all()
    return _rendre(request, "admin/offres.html", {
        **_profil_admin(admin),
        "page_active": "offres",
        "formations": [{"id": f.id, "titre": f.titre} for f in formations],
    })
