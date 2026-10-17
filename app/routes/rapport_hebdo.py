"""Compte-rendu hebdomadaire envoyé par e-mail (chaque lundi matin), même s'il ne
s'est rien passé.

Déclenché par une tâche planifiée GitHub Actions (.github/workflows/rapport-hebdo.yml)
qui appelle POST /cron/rapport-hebdo avec l'en-tête X-Cron-Token = variable
d'environnement CRON_TOKEN (Render) = secret CRON_TOKEN (GitHub).

Contenu (7 derniers jours) : paiements reçus / en attente, nouvelles inscriptions,
accès ouverts, chapitres validés, réponses aux questionnaires. Contrôle Stripe :
chaque paiement réussi chez Stripe doit correspondre à une commande payée sur la
plateforme ; sinon l'accès est ouvert automatiquement et c'est signalé.

Destinataires : variable RAPPORT_DESTINATAIRES (adresses séparées par des virgules),
à défaut EMAIL_ADMIN.
"""
import hmac
import logging
import os
from datetime import datetime, timedelta
from html import escape

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from ..database import obtenir_session
from ..models import Eleve, AccesFormation, ValidationChapitre, ReponseChapitre
from .boutique_models import Commande
from .. import emails

logger = logging.getLogger(__name__)
router = APIRouter()


def _fr(dt):
    if not dt:
        return ""
    try:
        from zoneinfo import ZoneInfo
        from datetime import timezone
        return dt.replace(tzinfo=timezone.utc).astimezone(ZoneInfo("Europe/Paris")).strftime("%d/%m %H:%M")
    except Exception:
        return dt.strftime("%d/%m %H:%M")


def _euros(x):
    return ("%.2f" % float(x or 0)).replace(".", ",").replace(",00", "") + " €"


def _controle_stripe(session: Session, depuis: datetime) -> list:
    """Paiements réussis chez Stripe sans commande payée côté plateforme -> on
    les traite (ouverture d'accès) et on les signale. Renvoie des lignes texte."""
    import stripe
    if not stripe.api_key:
        return ["Contrôle Stripe impossible : clé STRIPE_SECRET_KEY absente."]
    from .boutique_paiement import traiter_session_stripe_payee, _en_dict
    alertes = []
    try:
        sessions = stripe.checkout.Session.list(created={"gte": int(depuis.timestamp())}, limit=100)
        for s in sessions.auto_paging_iter():
            d = _en_dict(s)
            if d.get("payment_status") != "paid":
                continue
            cmd = session.query(Commande).filter_by(stripe_session_id=d.get("id")).first()
            if cmd and cmd.statut == "payee":
                continue
            traiter_session_stripe_payee(session, d)
            alertes.append("Paiement Stripe %s (%s) n'était pas enregistré : accès ouvert automatiquement."
                           % (_euros((d.get("amount_total") or 0) / 100), d.get("customer_email") or "?"))
    except Exception as e:
        logger.error("Contrôle Stripe rapport hebdo : %s", e)
        alertes.append("Contrôle Stripe impossible cette semaine (%s)." % str(e)[:120])
    return alertes


def construire_rapport(session: Session, controle_stripe: bool = True) -> tuple:
    fin = datetime.utcnow()
    debut = fin - timedelta(days=7)

    alertes = _controle_stripe(session, debut) if controle_stripe else []
    payees = session.query(Commande).filter(Commande.statut == "payee", Commande.payee_le >= debut).all()
    attente = session.query(Commande).filter(Commande.statut != "payee", Commande.cree_le >= debut).all()
    inscrits = session.query(Eleve).filter(Eleve.cree_le >= debut).all()
    acces = session.query(AccesFormation).filter(AccesFormation.accorde_le >= debut).all()
    nb_valid = session.query(ValidationChapitre).filter(ValidationChapitre.valide_le >= debut).count()
    reponses = session.query(ReponseChapitre).filter(ReponseChapitre.maj_le >= debut).all()

    def eleve_de(cmd):
        e = session.get(Eleve, cmd.eleve_id)
        return ("%s %s" % (e.prenom or "", e.nom or "")).strip() if e else "?"

    def libelle(cmd):
        if cmd.offre_id:
            from ..models import Offre
            o = session.get(Offre, cmd.offre_id)
            return (o.nom if o else "Offre") + (" (acompte)" if cmd.type_paiement == "acompte" else "")
        try:
            return ", ".join(l.tarif.formation.titre for l in cmd.lignes) or "Commande"
        except Exception:
            return "Commande"

    rien = not (payees or attente or inscrits or acces or nb_valid or reponses or alertes)
    total = sum(float(c.montant_total or 0) for c in payees)

    def section(titre, lignes, vide="Aucun."):
        corps = "".join('<li style="margin:3px 0;">%s</li>' % l for l in lignes) if lignes else \
            '<li style="color:#999;list-style:none;">%s</li>' % vide
        return ('<h3 style="color:#B8922A;font-size:15px;margin:22px 0 6px;">%s</h3>'
                '<ul style="margin:0;padding-left:18px;color:#2E2210;font-size:14px;">%s</ul>' % (titre, corps))

    html = ['<div style="font-family:Georgia,serif;max-width:640px;margin:0 auto;padding:30px;'
            'background:#FDFAF5;border-radius:12px;border:1px solid #e8dfc8;">',
            '<h2 style="color:#B8922A;margin:0 0 4px;">Compte-rendu de la semaine</h2>',
            '<p style="color:#888;margin:0 0 18px;font-size:13px;">Du %s au %s (heure de Paris)</p>' % (_fr(debut), _fr(fin))]
    if alertes:
        html.append('<div style="background:#F8E1DC;border:1px solid #e3b5a8;border-radius:8px;padding:12px 14px;'
                    'color:#A1432A;font-size:14px;margin-bottom:10px;"><strong>⚠️ À vérifier</strong><br>%s</div>'
                    % "<br>".join(escape(a) for a in alertes))
    if rien:
        html.append('<p style="font-size:16px;color:#2E2210;background:#fff;border:1px solid #e8dfc8;border-radius:8px;'
                    'padding:14px 16px;">🌿 Rien à signaler cette semaine : aucun paiement, aucune inscription, '
                    'aucune activité élève. Tout fonctionne, simplement personne n\'est passé.</p>')
    else:
        html.append('<p style="font-size:15px;color:#2E2210;"><strong>%d paiement(s) reçu(s) — %s</strong></p>'
                    % (len(payees), _euros(total)))
        html.append(section("💳 Paiements reçus", ["%s — %s — <strong>%s</strong> (%s)" % (
            escape(eleve_de(c)), escape(libelle(c)), _euros(c.montant_total), _fr(c.payee_le)) for c in payees]))
        html.append(section("⏳ Paiements commencés mais non aboutis", ["%s — %s — %s (%s)" % (
            escape(eleve_de(c)), escape(libelle(c)), _euros(c.montant_total), _fr(c.cree_le)) for c in attente],
            "Aucun."))
        html.append(section("🆕 Nouvelles inscriptions", ["%s %s (%s)" % (
            escape(e.prenom or ""), escape(e.nom or ""), escape(e.email or "")) for e in inscrits]))
        html.append(section("🔓 Accès ouverts", ["%s → %s" % (
            escape(eleve_de(a)), escape(a.formation.titre if a.formation else "?")) for a in acces]))
        html.append(section("📝 Réponses aux questionnaires", ["%s — %s" % (
            escape(eleve_de(r)), escape(r.chapitre.titre if r.chapitre else "?")) for r in reponses]))
        html.append('<p style="color:#2E2210;font-size:14px;margin-top:18px;">✅ Chapitres validés par les élèves : <strong>%d</strong></p>' % nb_valid)
    html.append('<p style="font-size:12px;color:#aaa;margin-top:26px;border-top:1px solid #e8dfc8;padding-top:14px;">'
                'Envoi automatique chaque lundi — Plateforme de formation laurence-mermet-bijon.fr. '
                'Détail des paiements : Stripe, compte MERMET-BIJON (identifiant laurencemb@orange.fr).</p></div>')
    sujet = ("Compte-rendu de la semaine — rien à signaler" if rien else
             "Compte-rendu de la semaine — %d paiement(s), %s" % (len(payees), _euros(total)))
    if alertes:
        sujet = "⚠️ " + sujet
    return sujet, "".join(html)


def _verifier_jeton(x_cron_token: str):
    attendu = os.environ.get("CRON_TOKEN", "")
    if not attendu:
        raise HTTPException(status_code=503, detail="CRON_TOKEN non configuré.")
    if not hmac.compare_digest(x_cron_token or "", attendu):
        raise HTTPException(status_code=403, detail="Jeton invalide.")


@router.post("/cron/rapport-hebdo")
def envoyer_rapport_hebdo(x_cron_token: str = Header(""), session: Session = Depends(obtenir_session)):
    _verifier_jeton(x_cron_token)
    sujet, corps = construire_rapport(session)
    dest = [d.strip() for d in os.environ.get("RAPPORT_DESTINATAIRES", "").split(",") if d.strip()] or [emails.EMAIL_ADMIN]
    envoyes = [d for d in dest if emails._envoyer_email(d, sujet, corps)]
    return {"ok": True, "sujet": sujet, "envoye_a": envoyes}


@router.get("/cron/rapport-hebdo/apercu", response_class=HTMLResponse)
def apercu_rapport_hebdo(x_cron_token: str = Header(""), session: Session = Depends(obtenir_session)):
    _verifier_jeton(x_cron_token)
    sujet, corps = construire_rapport(session, controle_stripe=False)
    return "<h3>%s</h3>%s" % (escape(sujet), corps)
