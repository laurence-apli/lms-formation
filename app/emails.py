"""
Module d'envoi d'emails via l'API Resend.
Utilisé pour :
- La réinitialisation du mot de passe élève
- La réinitialisation du mot de passe administrateur

Configuration requise :
- Variable d'environnement RESEND_API_KEY (clé commençant par re_...)
- Variable d'environnement EMAIL_EXPEDITEUR (ex: onboarding@resend.dev en mode test,
  ou formation@laurence-mermet-bijon.fr une fois le domaine vérifié)
"""
import os
import urllib.request
import urllib.error
import json
import logging

logger = logging.getLogger(__name__)

RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
EMAIL_EXPEDITEUR = os.environ.get("EMAIL_EXPEDITEUR", "onboarding@resend.dev")
NOM_EXPEDITEUR = os.environ.get("NOM_EXPEDITEUR", "Laurence Mermet-Bijon — Formation")


def _envoyer_email(destinataire: str, sujet: str, corps_html: str) -> bool:
    """
    Envoie un email via l'API Resend.
    Retourne True si l'envoi a réussi, False sinon.
    N'interrompt jamais le flux principal — les erreurs sont loguées.
    """
    if not RESEND_API_KEY:
        logger.warning("RESEND_API_KEY non configurée — email non envoyé à %s", destinataire)
        return False

    payload = json.dumps({
        "from": f"{NOM_EXPEDITEUR} <{EMAIL_EXPEDITEUR}>",
        "to": [destinataire],
        "subject": sujet,
        "html": corps_html,
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=payload,
        headers={
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; LMS-Formation/1.0)",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status in (200, 201):
                logger.info("Email envoyé avec succès à %s", destinataire)
                return True
            else:
                logger.error("Erreur Resend %s pour %s", resp.status, destinataire)
                return False
    except urllib.error.HTTPError as e:
        corps_erreur = e.read().decode("utf-8", errors="replace")
        logger.error("Erreur HTTP Resend %s pour %s : %s", e.code, destinataire, corps_erreur)
        return False
    except Exception as e:
        logger.error("Erreur inattendue envoi email à %s : %s", destinataire, str(e))
        return False
