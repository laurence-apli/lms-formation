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
from ..models import Offre, Formation, Eleve
from ..routes.auth import admin_connecte
from ..config import URL_SITE_VITRINE
from ..routes.boutique_models import Commande

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


@router.get("/paiements", response_class=HTMLResponse)
def page_paiements(request: Request, admin=Depends(admin_connecte)):
    return templates.TemplateResponse(
        request, "admin/paiements.html",
        {"profil": {"prenom": admin.prenom, "nom": admin.nom}, "page_active": "paiements", "url_site_vitrine": URL_SITE_VITRINE}
    )


@router.get("/api/paiements")
def api_paiements(session: Session = Depends(obtenir_session), admin=Depends(admin_connecte)):
    from sqlalchemy.orm import joinedload
    from datetime import datetime as dt
    commandes = (
        session.query(Commande)
        .options(joinedload(Commande.eleve))
        .order_by(Commande.cree_le.desc())
        .all()
    )
    result = []
    for c in commandes:
        if not c.eleve:
            continue
        # Description
        if c.offre_id:
            offre = session.get(Offre, c.offre_id)
            desc = offre.nom if offre else f"Offre #{c.offre_id}"
        else:
            desc = ", ".join(lc.tarif.formation.titre if hasattr(lc, 'tarif') and lc.tarif and hasattr(lc.tarif, 'formation') and lc.tarif.formation else "Formation" for lc in (c.lignes or [])) or "Achat boutique"
        # Reste dû (acompte seulement)
        reste_du = 0.0
        if c.type_paiement == "acompte" and c.statut not in ("annulee", "payee"):
            if c.offre_id:
                offre = session.get(Offre, c.offre_id)
                if offre:
                    reste_du = float(offre.prix_total) - float(c.montant_total)
            elif getattr(c, "montant_prix_total", None):
                reste_du = float(c.montant_prix_total) - float(c.montant_total)  # noqa
        result.append({
            "id": c.id,
            "date": c.cree_le.strftime("%d/%m/%Y") if c.cree_le else "",
            "prenom": c.eleve.prenom,
            "nom": c.eleve.nom,
            "email": c.eleve.email,
            "description": desc,
            "type_paiement": c.type_paiement,
            "montant_total": float(c.montant_total),
            "reste_du": reste_du,
            "statut": c.statut,
        })
    return result


class PaiementManuelIn(BaseModel):
    email: str
    prenom: str
    nom: str
    description: str
    montant_verse: float
    montant_prix_total: float | None = None
    type_paiement: str = "comptant"  # "comptant" ou "acompte"
    moyen_paiement: str = "virement"  # "virement", "cheque", "especes", "cabinet"
    note: str = ""


@router.post("/api/paiements/manuel")
def enregistrer_paiement_manuel(
    data: PaiementManuelIn,
    session: Session = Depends(obtenir_session),
    admin=Depends(admin_connecte),
):
    from ..models import Eleve as EleveModel
    import bcrypt as _bcrypt, secrets
    from decimal import Decimal
    # Trouver ou créer l'élève
    eleve = session.query(EleveModel).filter_by(email=data.email.lower().strip()).first()
    if not eleve:
        eleve = EleveModel(
            prenom=data.prenom,
            nom=data.nom,
            email=data.email.lower().strip(),
            mot_de_passe_hash=_bcrypt.hashpw(secrets.token_hex(16).encode(), _bcrypt.gensalt()).decode(),
            actif=True,
        )
        session.add(eleve)
        session.flush()
    commande = Commande(
        eleve_id=eleve.id,
        montant_total=Decimal(str(data.montant_verse)),
        montant_prix_total=Decimal(str(data.montant_prix_total)) if data.montant_prix_total else None,
        type_paiement=data.type_paiement,
        moyen_paiement=data.moyen_paiement,
        note=data.note,
        statut="payee" if data.type_paiement == "comptant" else "acompte_verse",
    )
    session.add(commande)
    session.commit()
    return {"ok": True, "commande_id": commande.id, "eleve_id": eleve.id}


class LienPaiementIn(BaseModel):
    description: str
    montant: float
    email_client: str | None = None
    prenom_client: str | None = None
    nom_client: str | None = None


@router.post("/api/paiements/lien-stripe")
def creer_lien_stripe(
    data: LienPaiementIn,
    session: Session = Depends(obtenir_session),
    admin=Depends(admin_connecte),
):
    import os, stripe as _stripe
    _stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
    if not _stripe.api_key:
        raise HTTPException(status_code=500, detail="STRIPE_SECRET_KEY non configurée")
    try:
        # Trouver ou créer le customer Stripe
        customer_id = None
        if data.email_client:
            customers = _stripe.Customer.list(email=data.email_client, limit=1)
            if customers.data:
                customer_id = customers.data[0].id
            else:
                name_parts = []
                if data.prenom_client:
                    name_parts.append(data.prenom_client)
                if data.nom_client:
                    name_parts.append(data.nom_client)
                cust = _stripe.Customer.create(
                    email=data.email_client,
                    name=" ".join(name_parts) or None,
                )
                customer_id = cust.id

        # Créer une facture Stripe avec un élément de ligne
        invoice_params = dict(
            collection_method="send_invoice",
            days_until_due=7,
        )
        if customer_id:
            invoice_params["customer"] = customer_id

        invoice = _stripe.Invoice.create(**invoice_params)

        # Ajouter la ligne
        item_params = dict(
            invoice=invoice.id,
            amount=int(round(data.montant * 100)),
            currency="eur",
            description=data.description,
        )
        if customer_id:
            item_params["customer"] = customer_id
        _stripe.InvoiceItem.create(**item_params)

        # Finaliser (génère le PDF + lien de paiement)
        invoice = _stripe.Invoice.finalize_invoice(invoice.id)

        return {
            "url": invoice.hosted_invoice_url,
            "invoice_id": invoice.id,
            "invoice_pdf": invoice.invoice_pdf,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
