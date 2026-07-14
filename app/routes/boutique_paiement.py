"""
Routes de paiement -- création de la session Stripe (achat neuf OU montée en
niveau), et webhook qui active automatiquement les accès une fois le
paiement confirmé.

À placer dans app/routes/boutique_paiement.py

⚠️ Nécessite d'ajouter "stripe" à requirements.txt (pip install stripe)
⚠️ Nécessite les variables d'environnement STRIPE_SECRET_KEY et
   STRIPE_WEBHOOK_SECRET sur Render (voir instructions_stripe.txt) --
   RIEN de tout ça ne fonctionnera avant la création du compte Stripe,
   mais le code peut être installé dès maintenant sans risque.
"""
import os
from datetime import datetime

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import obtenir_session
from ..models import Eleve, AccesFormation
from .boutique_models import TarifFormation, Commande, LigneCommande, calculer_panier
from .auth import eleve_connecte

router = APIRouter()

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
URL_SITE_VITRINE = os.environ.get("URL_SITE_VITRINE", "https://laurence-mermet-bijon.fr")
URL_PLATEFORME = os.environ.get("URL_PLATEFORME", "https://lms-formation.onrender.com")


class CreerPaiementRequete(BaseModel):
    tarif_ids: list[int]
    code_promo: str | None = None


@router.post("/eleve/panier/paiement")
def creer_session_paiement(
    requete: CreerPaiementRequete,
    eleve: Eleve = Depends(eleve_connecte),
    session: Session = Depends(obtenir_session),
):
    """Crée la session de paiement Stripe pour un achat neuf. Le montant
    n'est JAMAIS pris tel quel depuis ce que le client a vu à l'écran -- on
    recalcule tout ici, depuis la base de données, une dernière fois."""
    if not requete.tarif_ids:
        raise HTTPException(status_code=400, detail="Panier vide.")

    panier = calculer_panier(session, requete.tarif_ids, requete.code_promo, eleve.id)
    if panier["erreur_code"]:
        raise HTTPException(status_code=400, detail=panier["erreur_code"])
    if not panier["lignes"]:
        raise HTTPException(status_code=400, detail="Aucune formation valide dans le panier.")

    commande = Commande(
        eleve_id=eleve.id, montant_total=panier["total"], statut="en_attente",
        code_promo_utilise=panier["code_applique"],
    )
    session.add(commande)
    session.flush()
    for ligne in panier["lignes"]:
        session.add(LigneCommande(
            commande_id=commande.id, tarif_formation_id=ligne["tarif_id"], prix_paye=ligne["prix_final"],
        ))
    session.commit()

    line_items = [
        {
            "price_data": {
                "currency": "eur",
                "product_data": {"name": ligne["nom"]},
                "unit_amount": round(ligne["prix_final"] * 100),
            },
            "quantity": 1,
        }
        for ligne in panier["lignes"]
    ]

    payment_method_types = ["card"]
    if panier["trois_x_disponible"]:
        payment_method_types.append("alma")

    checkout_session = stripe.checkout.Session.create(
        mode="payment", payment_method_types=payment_method_types, line_items=line_items,
        customer_email=eleve.email,
        success_url=f"{URL_PLATEFORME}/eleve/paiement-confirme?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{URL_SITE_VITRINE}/pratiques.html",
        metadata={"commande_id": str(commande.id), "eleve_id": str(eleve.id)},
    )

    commande.stripe_session_id = checkout_session.id
    session.commit()
    return {"checkout_url": checkout_session.url}


class MonteeNiveauRequete(BaseModel):
    tarif_id: int  # le tarif du NOUVEAU niveau souhaité


@router.post("/eleve/montee-de-niveau/paiement")
def creer_session_paiement_montee_niveau(
    requete: MonteeNiveauRequete,
    eleve: Eleve = Depends(eleve_connecte),
    session: Session = Depends(obtenir_session),
):
    """Crée la session de paiement pour une MONTÉE DE NIVEAU -- montant
    recalculé ici (prix du nouveau palier moins ce qui a été réellement payé
    pour le palier actuel), jamais transmis tel quel depuis l'écran."""
    from .boutique_models import propositions_montee_niveau

    propositions = propositions_montee_niveau(session, eleve.id)
    proposition = next((p for p in propositions if p["tarif_id"] == requete.tarif_id), None)
    if proposition is None:
        raise HTTPException(status_code=400, detail="Cette montée de niveau n'est pas disponible pour ton compte.")

    montant = proposition["difference_a_payer"]
    if montant <= 0:
        raise HTTPException(status_code=400, detail="Aucun montant à payer pour cette montée de niveau.")

    tarif = session.get(TarifFormation, requete.tarif_id)
    commande = Commande(
        eleve_id=eleve.id, montant_total=montant, statut="en_attente",
    )
    session.add(commande)
    session.flush()
    session.add(LigneCommande(commande_id=commande.id, tarif_formation_id=tarif.id, prix_paye=montant))
    session.commit()

    payment_method_types = ["card"]
    if tarif.autoriser_3x:
        payment_method_types.append("alma")

    checkout_session = stripe.checkout.Session.create(
        mode="payment", payment_method_types=payment_method_types,
        line_items=[{
            "price_data": {
                "currency": "eur",
                "product_data": {"name": f"{proposition['formation_titre']} — montée vers {proposition['nom_option']}"},
                "unit_amount": round(montant * 100),
            },
            "quantity": 1,
        }],
        customer_email=eleve.email,
        success_url=f"{URL_PLATEFORME}/eleve/paiement-confirme?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{URL_PLATEFORME}/eleve/tableau-de-bord",
        metadata={"commande_id": str(commande.id), "eleve_id": str(eleve.id)},
    )
    commande.stripe_session_id = checkout_session.id
    session.commit()
    return {"checkout_url": checkout_session.url}


@router.post("/webhooks/stripe")
async def webhook_stripe(request: Request, session: Session = Depends(obtenir_session)):
    """Stripe appelle cette route automatiquement quand un paiement est
    confirmé. C'est ICI que les accès sont réellement activés (ou mis à
    jour vers un niveau supérieur) -- jamais avant, jamais depuis le
    navigateur du client."""
    payload = await request.body()
    signature = request.headers.get("stripe-signature")
    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "")

    try:
        event = stripe.Webhook.construct_event(payload, signature, webhook_secret)
    except (ValueError, stripe.error.SignatureVerificationError):
        raise HTTPException(status_code=400, detail="Signature webhook invalide.")

    if event["type"] == "checkout.session.completed":
        stripe_session = event["data"]["object"]
        commande_id = stripe_session["metadata"].get("commande_id")
        commande = session.get(Commande, int(commande_id)) if commande_id else None

        if commande and commande.statut != "payee":
            commande.statut = "payee"
            commande.payee_le = datetime.utcnow()
            commande.moyen_paiement = stripe_session.get("payment_method_types", ["card"])[0]
            session.commit()

            for ligne in commande.lignes:
                tarif = session.get(TarifFormation, ligne.tarif_formation_id)
                acces_existant = (
                    session.query(AccesFormation)
                    .filter_by(eleve_id=commande.eleve_id, formation_id=tarif.formation_id)
                    .first()
                )
                if acces_existant:
                    # Montée de niveau : on ne remplace le niveau que s'il est
                    # réellement supérieur (sécurité contre tout rejeu de webhook).
                    if tarif.niveau > acces_existant.niveau:
                        acces_existant.niveau = tarif.niveau
                else:
                    session.add(AccesFormation(
                        eleve_id=commande.eleve_id, formation_id=tarif.formation_id, niveau=tarif.niveau,
                    ))
            session.commit()

    return {"ok": True}
