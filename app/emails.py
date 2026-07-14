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
            # CORRECTION : sans en-tête User-Agent, Cloudflare (qui protège
            # l'API Resend) rejette parfois la requête avec une erreur 1010
            # ("Access Denied: Bad Bot") -- ajouté pour ressembler à une
            # requête standard plutôt qu'à un script sans identification.
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


def email_reinitialisation_mot_de_passe(destinataire: str, prenom: str, lien: str) -> bool:
    """
    Envoie un email de réinitialisation de mot de passe à un élève ou administrateur.
    """
    sujet = "Réinitialisation de votre mot de passe — Espace Formation"

    corps_html = f"""
<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin:0; padding:0; background:#F5EDD6; font-family:'Georgia', serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#F5EDD6; padding:40px 20px;">
    <tr>
      <td align="center">
        <table width="560" cellpadding="0" cellspacing="0" style="background:#FFFFFF; border-radius:12px; overflow:hidden; box-shadow:0 4px 20px rgba(0,0,0,0.08);">

          <!-- En-tête dorée -->
          <tr>
            <td style="background:#2E2210; padding:28px 40px; text-align:center;">
              <p style="margin:0; font-family:Georgia, serif; font-size:22px; font-weight:600; color:#F5EDD6; letter-spacing:0.5px;">
                Espace Formation
              </p>
              <p style="margin:6px 0 0; font-family:Arial, sans-serif; font-size:11px; font-weight:600; letter-spacing:3px; color:#B8922A; text-transform:uppercase;">
                Laurence Mermet-Bijon
              </p>
            </td>
          </tr>

          <!-- Bande dorée -->
          <tr>
            <td style="background:linear-gradient(90deg, #B8922A, #C47B6E); height:4px;"></td>
          </tr>

          <!-- Corps -->
          <tr>
            <td style="padding:40px 40px 32px;">
              <p style="margin:0 0 20px; font-size:17px; color:#2E2210; line-height:1.6;">
                Bonjour {prenom},
              </p>
              <p style="margin:0 0 20px; font-size:15px; color:#3a2f1a; line-height:1.7;">
                Vous avez demandé à réinitialiser votre mot
