"""
Page publique d'inscription et paiement pour une offre.
"""
import json
import logging
import secrets
from decimal import Decimal

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import bcrypt as _bcrypt
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import obtenir_session
from ..models import Offre, Eleve, Formation
from ..routes.boutique_models import Commande
import os
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
URL_PLATEFORME = os.environ.get("URL_PLATEFORME", "http://localhost:8000")

logger = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

stripe.api_key = STRIPE_SECRET_KEY


class CheckoutOffreIn(BaseModel):
    prenom: str
    nom: str
    email: str
    type_paiement: str  # 'comptant' ou 'acompte'


@router.get("/offre/{slug}", response_class=HTMLResponse)
def page_offre(request: Request, slug: str, session: Session = Depends(obtenir_session)):
    offre = session.query(Offre).filter_by(slug=slug, actif=True).first()
    if not offre:
        raise HTTPException(status_code=404, detail="Cette offre n'est pas disponible.")

    formations = []
    if offre.formations_ids:
        for fid in json.loads(offre.formations_ids):
            f = session.query(Formation).filter_by(id=fid, actif=True).first()
            if f:
                formations.append(f.titre)

    return templates.TemplateResponse(request, "offre_publique.html", {
        "offre": {
            "id": offre.id,
            "slug": offre.slug,
            "nom": offre.nom,
            "description": offre.description or "",
            "points_inclus": json.loads(offre.points_inclus or "[]"),
            "prix_total": float(offre.prix_total),
            "montant_acompte": float(offre.montant_acompte) if offre.montant_acompte else None,
            "image_url": offre.image_url,
            "formations": formations,
        }
    })


@router.post("/offre/{slug}/checkout")
def checkout_offre(slug: str, data: CheckoutOffreIn, session: Session = Depends(obtenir_session)):
    offre = session.query(Offre).filter_by(slug=slug, actif=True).first()
    if not offre:
        raise HTTPException(status_code=404, detail="Offre introuvable")

    prenom = data.prenom.strip()
    nom = (data.nom or prenom).strip()
    email = data.email.strip().lower()

    if not prenom or not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Prénom et email valide obligatoires")

    if data.type_paiement == "acompte" and not offre.montant_acompte:
        raise HTTPException(status_code=400, detail="Acompte non disponible pour cette offre")

    montant = offre.montant_acompte if data.type_paiement == "acompte" else offre.prix_total

    # Créer ou récupérer le compte élève
    eleve = session.query(Eleve).filter_by(email=email).first()
    compte_cree = False
    if not eleve:
        eleve = Eleve(
            prenom=prenom,
            nom=nom,
            email=email,
            mot_de_passe_hash=_bcrypt.hashpw(secrets.token_hex(16).encode(), _bcrypt.gensalt()).decode(),
            actif=False,  # activé par le webhook après paiement
        )
        session.add(eleve)
        session.flush()
        compte_cree = True

    # Créer la commande en attente
    commande = Commande(
        eleve_id=eleve.id,
        montant_total=montant,
        offre_id=offre.id,
        type_paiement=data.type_paiement,
        statut="en_attente",
        moyen_paiement="stripe",
    )
    session.add(commande)
    session.flush()

    # Session Stripe Checkout
    url_base = URL_PLATEFORME.rstrip("/")
    checkout = stripe.checkout.Session.create(
        payment_method_types=["card", "klarna"],
        line_items=[{
            "price_data": {
                "currency": "eur",
                "unit_amount": int(montant * 100),
                "product_data": {
                    "name": offre.nom,
                    "description": ("Acompte — " if data.type_paiement == "acompte" else "") + (offre.description or offre.nom),
                },
            },
            "quantity": 1,
        }],
        mode="payment",
        success_url=f"{url_base}/eleve/connexion?inscription=ok",
        cancel_url=f"{url_base}/offre/{slug}",
        customer_email=email,
        metadata={
            "type": "offre_publique",
            "offre_id": str(offre.id),
            "eleve_id": str(eleve.id),
            "commande_id": str(commande.id),
            "type_paiement": data.type_paiement,
            "compte_cree": "1" if compte_cree else "0",
        },
    )

    commande.stripe_session_id = checkout.id
    session.commit()
    return {"checkout_url": checkout.url}
