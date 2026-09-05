"""
Routes de paiement -- création de la session Stripe (achat neuf OU montée en
niveau, éventuellement combinés dans le même panier), et webhook qui active
automatiquement les accès une fois le paiement confirmé.

À placer dans app/routes/boutique_paiement.py

⚠️ Nécessite d'ajouter "stripe" à requirements.txt (pip install stripe)
⚠️ Nécessite les variables d'environnement STRIPE_SECRET_KEY et
STRIPE_WEBHOOK_SECRET sur Render (voir instructions_stripe.txt) --
RIEN de tout ça ne fonctionnera avant la création du compte Stripe,
mais le code peut être installé dès maintenant sans risque.

⚠️ MODE_SIMULATION_PAIEMENT (ci-dessous) : tant que Stripe n'est pas branché,
mettre ce drapeau à True fait que "Passer au paiement" active directement les
accès, comme si le paiement avait réussi -- pratique pour tester tout le
parcours (achat, montée de niveau, décompte des séances...) sans compte
Stripe. Le jour où Stripe est prêt, il suffit de repasser ce drapeau à False
-- tout le code Stripe ci-dessous reste inchangé et se réactive tel quel.
"""
import os
from datetime import datetime

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import obtenir_session
from ..models import Eleve, AccesFormation, Offre
from .boutique_models import TarifFormation, Commande, LigneCommande, calculer_panier
from .auth import eleve_connecte
from ..emails import email_notification_paiement_reussi, email_notification_paiement_echoue
router = APIRouter()

MODE_SIMULATION_PAIEMENT = False # ✅ Stripe actif — paiements réels

# Tant que MODE_SIMULATION_PAIEMENT est actif, seuls ces comptes de test
# peuvent valider un paiement simulé. Tous les autres reçoivent un message
# "paiement indisponible" -- évite que n'importe quel élève obtienne un
# accès gratuit pendant la phase de test des solutions de paiement.
EMAILS_TEST_PAIEMENT = {
"laurencemb42@gmail.com",
"chatagnon_fab@hotmail.com",
"maresonance42@gmail.com",
"n.chatagnon2804@gmail.com",
}

stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
URL_SITE_VITRINE = os.environ.get("URL_SITE_VITRINE", "https://laurence-mermet-bijon.fr")
URL_PLATEFORME = os.environ.get("URL_PLATEFORME", "https://lms-formation.onrender.com")

def activer_acces_commande(session: Session, commande: Commande) -> None:
    """Active (ou met à niveau) les accès formation pour toutes les lignes
    d'une commande marquée payée -- utilisé aussi bien par le webhook Stripe
    réel que par le mode simulation, pour ne jamais dupliquer cette logique
    à deux endroits. Ne fait rien si la commande n'est pas (ou plus)
    marquée payée, par sécurité."""
    if commande.statut != "payee":
        return
    for ligne in commande.lignes:
        tarif = session.get(TarifFormation, ligne.tarif_formation_id)
        acces_existant = (
            session.query(AccesFormation)
            .filter_by(eleve_id=commande.eleve_id, formation_id=tarif.formation_id)
            .first()
        )
        if acces_existant:
            if tarif.niveau > acces_existant.niveau:
                acces_existant.niveau = tarif.niveau
        else:
            session.add(AccesFormation(
                eleve_id=commande.eleve_id, formation_id=tarif.formation_id, niveau=tarif.niveau,
            ))
    session.commit()

    eleve = session.get(Eleve, commande.eleve_id)
    description = ", ".join(
        (f"{l.tarif.formation.titre} — {l.tarif.nom_option}" if l.tarif.nom_option != "Tarif unique" else l.tarif.formation.titre)
        for l in commande.lignes
    )
    email_notification_paiement_reussi(f"{eleve.prenom} {eleve.nom}", eleve.email, description, float(commande.montant_total))
    # Email de confirmation à l'élève (boutique)
    try:
        from ..emails import email_confirmation_achat_eleve
        email_confirmation_achat_eleve(eleve.prenom, eleve.email, description, float(commande.montant_total), est_acompte=False, compte_nouveau=False)
    except Exception as e:
        logger.error(f"Erreur email confirmation boutique: {e}")

class CreerPaiementRequete(BaseModel):
    tarif_ids: list[int] = []
    montee_tarif_ids: list[int] = []
    code_promo: str | None = None

@router.post("/eleve/panier/apercu")
def apercu_panier_eleve(
    requete: CreerPaiementRequete,
    eleve: Eleve = Depends(eleve_connecte),
    session: Session = Depends(obtenir_session),
):
    """Aperçu du panier pour l'élève connecté -- même calcul que le paiement,
    sans créer de commande ni lancer Stripe. Utilisé par le catalogue
    pour afficher le total et valider le code promo en temps réel."""
    return calculer_panier(session, requete.tarif_ids, requete.code_promo, eleve.id, requete.montee_tarif_ids)

@router.post("/eleve/panier/paiement")
def creer_session_paiement(
    requete: CreerPaiementRequete,
    eleve: Eleve = Depends(eleve_connecte),
    session: Session = Depends(obtenir_session),
):
    """Crée la session de paiement Stripe pour un panier -- achats neufs et/ou
    montées de niveau. Le montant n'est JAMAIS pris tel quel depuis ce que le
    client a vu à l'écran -- on recalcule tout ici, depuis la base de
    données, une dernière fois."""
    if not requete.tarif_ids and not requete.montee_tarif_ids:
        raise HTTPException(status_code=400, detail="Panier vide.")

    panier = calculer_panier(session, requete.tarif_ids, requete.code_promo, eleve.id, requete.montee_tarif_ids)
    if panier["erreur_code"]:
        raise HTTPException(status_code=400, detail=panier["erreur_code"])
    if not panier["lignes"]:
        raise HTTPException(status_code=400, detail="Aucune formation valide dans le panier.")

    if MODE_SIMULATION_PAIEMENT and eleve.email not in EMAILS_TEST_PAIEMENT:
        email_notification_paiement_echoue(f"{eleve.prenom} {eleve.nom}", eleve.email, ", ".join(l["nom"] for l in panier["lignes"]), float(panier["total"]), "Tentative pendant la phase de test (Stripe non branche).")
        raise HTTPException(status_code=503, detail="Paiement indisponible pour le moment, merci de réessayer plus tard.")

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

    if MODE_SIMULATION_PAIEMENT:
        commande.statut = "payee"
        commande.payee_le = datetime.utcnow()
        commande.moyen_paiement = "simulation"
        commande.stripe_session_id = f"simulation-{commande.id}"
        session.commit()
        activer_acces_commande(session, commande)
        return {"checkout_url": f"{URL_PLATEFORME}/eleve/paiement-confirme?session_id={commande.stripe_session_id}"}

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
    if panier["total"] >= 180:
        payment_method_types.append("klarna")

    checkout_session = stripe.checkout.Session.create(
        mode="payment", payment_method_types=payment_method_types, line_items=line_items,
        customer_email=eleve.email,
        success_url=f"{URL_PLATEFORME}/eleve/paiement-confirme?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{URL_SITE_VITRINE}/pratiques.html",
        **({"custom_text": {"submit": {"message": "Paiement en 3 fois disponible avec Klarna"}}} if "klarna" in payment_method_types else {}),
    metadata={"commande_id": str(commande.id), "eleve_id": str(eleve.id)},
    )

    commande.stripe_session_id = checkout_session.id
    session.commit()
    return {"checkout_url": checkout_session.url}

class MonteeNiveauRequete(BaseModel):
    tarif_id: int # le tarif du NOUVEAU niveau souhaité

@router.post("/eleve/montee-de-niveau/paiement")
def creer_session_paiement_montee_niveau(
    requete: MonteeNiveauRequete,
    eleve: Eleve = Depends(eleve_connecte),
    session: Session = Depends(obtenir_session),
):
    """Ancienne route -- paiement direct pour UNE SEULE montée de niveau,
    sans passer par le panier. Conservée pour compatibilité ; le catalogue
    utilise désormais /eleve/panier/paiement pour tout combiner."""
    from .boutique_models import propositions_montee_niveau

    propositions = propositions_montee_niveau(session, eleve.id)
    proposition = next((p for p in propositions if p["tarif_id"] == requete.tarif_id), None)
    if proposition is None:
        raise HTTPException(status_code=400, detail="Cette montée de niveau n'est pas disponible pour ton compte.")

    montant = proposition["difference_a_payer"]
    if montant <= 0:
        raise HTTPException(status_code=400, detail="Aucun montant à payer pour cette montée de niveau.")

    if MODE_SIMULATION_PAIEMENT and eleve.email not in EMAILS_TEST_PAIEMENT:
        email_notification_paiement_echoue(f"{eleve.prenom} {eleve.nom}", eleve.email, f"{proposition['formation_titre']} — {proposition['nom_option']} (montee de niveau)", float(montant), "Tentative pendant la phase de test (Stripe non branche).")
        raise HTTPException(status_code=503, detail="Paiement indisponible pour le moment, merci de réessayer plus tard.")

    tarif = session.get(TarifFormation, requete.tarif_id)
    commande = Commande(
        eleve_id=eleve.id, montant_total=montant, statut="en_attente",
    )
    session.add(commande)
    session.flush()
    session.add(LigneCommande(commande_id=commande.id, tarif_formation_id=tarif.id, prix_paye=montant))
    session.commit()

    if MODE_SIMULATION_PAIEMENT:
        commande.statut = "payee"
        commande.payee_le = datetime.utcnow()
        commande.moyen_paiement = "simulation"
        commande.stripe_session_id = f"simulation-{commande.id}"
        session.commit()
        activer_acces_commande(session, commande)
        return {"checkout_url": f"{URL_PLATEFORME}/eleve/paiement-confirme?session_id={commande.stripe_session_id}"}

    payment_method_types = ["card"]
    if montant >= 180:
        payment_method_types.append("klarna")

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
    navigateur du client. (En mode simulation, ce webhook n'est jamais
    appelé -- c'est creer_session_paiement qui active directement les accès,
    voir plus haut.)"""
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
        metadata = stripe_session.get("metadata", {})

        if metadata.get("type") == "offre_publique":
            _activer_offre_apres_paiement(session, stripe_session, metadata)
        elif commande and commande.statut != "payee":
            commande.statut = "payee"
            commande.payee_le = datetime.utcnow()
            commande.moyen_paiement = stripe_session.get("payment_method_types", ["card"])[0]
            session.commit()
            activer_acces_commande(session, commande)

    elif event["type"] == "checkout.session.expired":
        stripe_session = event["data"]["object"]
        metadata = stripe_session.get("metadata", {})
        if metadata.get("type") == "offre_publique":
            eleve_id = int(metadata.get("eleve_id", 0))
            offre_id = int(metadata.get("offre_id", 0))
            eleve = session.get(Eleve, eleve_id) if eleve_id else None
            offre = session.query(Offre).filter_by(id=offre_id).first() if offre_id else None
            if eleve and offre:
                try:
                    from ..emails import email_notification_paiement_echoue, email_paiement_echoue_eleve
                    montant = stripe_session.get("amount_total", 0) / 100
                    email_notification_paiement_echoue(
                        f"{eleve.prenom} {eleve.nom}", eleve.email,
                        offre.nom, montant, "Session de paiement expirée ou abandonnée"
                    )
                    try:
                        email_paiement_echoue_eleve(eleve.prenom, eleve.email, offre.nom)
                    except Exception:
                        pass
                except Exception as e:
                    logger.error(f"Erreur email echec offre: {e}")

    return {"ok": True}


def _activer_offre_apres_paiement(session, stripe_session, metadata):
    import json
    from ..models import Eleve, AccesFormation, Offre
    eleve_id = int(metadata.get("eleve_id", 0))
    offre_id = int(metadata.get("offre_id", 0))
    commande_id = int(metadata.get("commande_id", 0))
    compte_cree = metadata.get("compte_cree") == "1"
    eleve = session.get(Eleve, eleve_id)
    offre = session.get(Offre, offre_id)
    commande = session.get(Commande, commande_id)
    if not eleve or not offre:
        logger.warning(f"Webhook offre_publique: eleve={eleve_id} ou offre={offre_id} introuvable")
        return
    eleve.actif = True
    if commande and commande.statut != "payee":
        commande.statut = "payee"
        commande.payee_le = datetime.utcnow()
        commande.moyen_paiement = stripe_session.get("payment_method_types", ["card"])[0]
    if offre.formations_ids:
        from ..models import Formation
        for fid in json.loads(offre.formations_ids):
            if not session.query(AccesFormation).filter_by(eleve_id=eleve.id, formation_id=fid).first():
                session.add(AccesFormation(eleve_id=eleve.id, formation_id=fid, niveau=1))
    session.commit()
    logger.info(f"Offre {offre_id} activee pour eleve {eleve_id}")
    # Email au nouvel élève pour définir son mot de passe
    if compte_cree:
        try:
            from ..routes.auth import _envoyer_email_definition_mdp
            _envoyer_email_definition_mdp(eleve, session)
        except Exception as e:
            logger.error(f"Erreur email mdp: {e}")
    # Email de notification à l'administrateur
    try:
        from ..emails import email_notification_paiement_reussi
        montant_paye = stripe_session.get("amount_total", 0) / 100
        type_p = metadata.get("type_paiement", "comptant")
        desc = f"{'Acompte' if type_p == 'acompte' else 'Paiement'} — {offre.nom}"
        email_notification_paiement_reussi(f"{eleve.prenom} {eleve.nom}", eleve.email, desc, montant_paye)
    except Exception as e:
        logger.error(f"Erreur email admin offre: {e}")
    # Email de confirmation à l'élève
    try:
        from ..emails import email_confirmation_achat_eleve
        montant_paye = stripe_session.get("amount_total", 0) / 100
        est_acompte = metadata.get("type_paiement") == "acompte"
        email_confirmation_achat_eleve(eleve.prenom, eleve.email, offre.nom, montant_paye, est_acompte, compte_cree)
    except Exception as e:
        logger.error(f"Erreur email confirmation eleve offre: {e}")
"""
Routes de paiement -- création de la session Stripe (achat neuf OU montée en
niveau, éventuellement combinés dans le même panier), et webhook qui active
automatiquement les accès une fois le paiement confirmé.

À placer dans app/routes/boutique_paiement.py

⚠️ Nécessite d'ajouter "stripe" à requirements.txt (pip install stripe)
⚠️ Nécessite les variables d'environnement STRIPE_SECRET_KEY et
STRIPE_WEBHOOK_SECRET sur Render (voir instructions_stripe.txt) --
RIEN de tout ça ne fonctionnera avant la création du compte Stripe,
mais le code peut être installé dès maintenant sans risque.

⚠️ MODE_SIMULATION_PAIEMENT (ci-dessous) : tant que Stripe n'est pas branché,
mettre ce drapeau à True fait que "Passer au paiement" active directement les
accès, comme si le paiement avait réussi -- pratique pour tester tout le
parcours (achat, montée de niveau, décompte des séances...) sans compte
Stripe. Le jour où Stripe est prêt, il suffit de repasser ce drapeau à False
-- tout le code Stripe ci-dessous reste inchangé et se réactive tel quel.
"""
import os
from datetime import datetime

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import obtenir_session
from ..models import Eleve, AccesFormation, Offre
from .boutique_models import TarifFormation, Commande, LigneCommande, calculer_panier
from .auth import eleve_connecte
from ..emails import email_notification_paiement_reussi, email_notification_paiement_echoue
