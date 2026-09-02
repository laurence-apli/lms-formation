"""
Routes admin pour la gestion des offres publiques de paiement.
"""
import json
import logging
import re
import base64
from decimal import Decimal
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="app/templates")
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import obtenir_session
from ..models import Offre, Formation
from ..routes.auth import admin_connecte
from ..config import URL_SITE_VITRINE

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/offres", response_class=HTMLResponse)
def page_offres(request: Request, admin=Depends(admin_connecte)):
    return templates.TemplateResponse(
        request, "admin/offres.html",
        {"profil": {"prenom": admin.prenom, "nom": admin.nom}, "page_active": "offres", "url_site_vitrine": URL_SITE_VITRINE}
    )


def _slugifier(nom: str) -> str:
    slug = nom.lower()
    for src, dst in [("àâä","a"),("éèêë","e"),("îï","i"),("ôö","o"),("ùûü","u"),("ç","c")]:
        for c in src:
            slug = slug.replace(c, dst)
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    return slug[:80]


class OffreIn(BaseModel):
    nom: str
    description: str = ""
    points_inclus: list[str] = []
    prix_total: float
    montant_acompte: float | None = None
    formations_ids: list[int] = []
    badge: str = "Accompagnement féminin"
    actif: bool = True


@router.get("/api/offres")
def lister_offres(session: Session = Depends(obtenir_session), admin=Depends(admin_connecte)):
    offres = session.query(Offre).order_by(Offre.cree_le.desc()).all()
    return [
        {
            "id": o.id,
            "slug": o.slug,
            "nom": o.nom,
            "description": o.description or "",
            "points_inclus": json.loads(o.points_inclus or "[]"),
            "prix_total": float(o.prix_total),
            "montant_acompte": float(o.montant_acompte) if o.montant_acompte else None,
            "image_url": o.image_url,
            "actif": o.actif,
            "formations_ids": json.loads(o.formations_ids or "[]"),
            "cree_le": o.cree_le.strftime("%d/%m/%Y") if o.cree_le else "",
            "badge": o.badge or "Accompagnement féminin",
            "lien": f"/offre/{o.slug}",
        }
        for o in offres
    ]


@router.post("/api/offres")
def creer_offre(data: OffreIn, session: Session = Depends(obtenir_session), admin=Depends(admin_connecte)):
    slug_base = _slugifier(data.nom)
    slug = slug_base
    i = 1
    while session.query(Offre).filter_by(slug=slug).first():
        slug = f"{slug_base}-{i}"
        i += 1

    offre = Offre(
        slug=slug,
        nom=data.nom,
        description=data.description,
        points_inclus=json.dumps(data.points_inclus, ensure_ascii=False),
        prix_total=Decimal(str(data.prix_total)),
        montant_acompte=Decimal(str(data.montant_acompte)) if data.montant_acompte else None,
        formations_ids=json.dumps(data.formations_ids),
        badge=data.badge,
        actif=data.actif,
    )
    session.add(offre)
    session.commit()
    session.refresh(offre)
    return {"id": offre.id, "slug": offre.slug, "lien": f"/offre/{offre.slug}"}


@router.put("/api/offres/{offre_id}")
def modifier_offre(
    offre_id: int, data: OffreIn,
    session: Session = Depends(obtenir_session), admin=Depends(admin_connecte)
):
    offre = session.query(Offre).filter_by(id=offre_id).first()
    if not offre:
        raise HTTPException(status_code=404, detail="Offre introuvable")
    offre.nom = data.nom
    offre.description = data.description
    offre.points_inclus = json.dumps(data.points_inclus, ensure_ascii=False)
    offre.prix_total = Decimal(str(data.prix_total))
    offre.montant_acompte = Decimal(str(data.montant_acompte)) if data.montant_acompte else None
    offre.formations_ids = json.dumps(data.formations_ids)
    offre.badge = data.badge
    offre.actif = data.actif
    session.commit()
    return {"ok": True}


@router.post("/api/offres/{offre_id}/toggle-actif")
def toggle_offre(offre_id: int, session: Session = Depends(obtenir_session), admin=Depends(admin_connecte)):
    offre = session.query(Offre).filter_by(id=offre_id).first()
    if not offre:
        raise HTTPException(status_code=404, detail="Offre introuvable")
    offre.actif = not offre.actif
    session.commit()
    return {"actif": offre.actif}


@router.post("/api/offres/{offre_id}/image")
async def uploader_image_offre(
    offre_id: int,
    fichier: UploadFile = File(...),
    session: Session = Depends(obtenir_session),
    admin=Depends(admin_connecte),
):
    offre = session.query(Offre).filter_by(id=offre_id).first()
    if not offre:
        raise HTTPException(status_code=404, detail="Offre introuvable")
    data = await fichier.read()
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Image trop lourde (max 5 Mo)")
    data_uri = f"data:{fichier.content_type};base64,{base64.b64encode(data).decode()}"
    offre.image_url = data_uri
    session.commit()
    return {"ok": True}


@router.delete("/api/offres/{offre_id}")
def supprimer_offre(offre_id: int, session: Session = Depends(obtenir_session), admin=Depends(admin_connecte)):
    offre = session.query(Offre).filter_by(id=offre_id).first()
    if not offre:
        raise HTTPException(status_code=404, detail="Offre introuvable")
    session.delete(offre)
    session.commit()
    return {"ok": True}
