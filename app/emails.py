"""
Envoi d'e-mails via Resend (https://resend.com).

Tant que RESEND_API_KEY n'est pas configurée (variable d'environnement),
les e-mails sont simplement affichés dans les journaux du serveur au lieu
d'être réellement envoyés -- ce qui permet de tester tout le système de
comptes (première connexion, réinitialisation) avant même d'avoir créé
le compte Resend.
"""
import logging
import httpx
from .config import RESEND_API_KEY, EMAIL_EXPEDITEUR

logger = logging.getLogger("emails")


def envoyer_email(destinataire: str, sujet: str, corps_html: str) -> bool:
    """Envoie un e-mail. Renvoie True si l'envoi a réussi (ou a été simulé
    avec succès), False en cas d'échec réel."""
    if not RESEND_API_KEY:
        # Mode simulation : utile en développement, avant d'avoir créé le
        # compte Resend -- on voit le contenu de l'e-mail dans les logs,
        # sans qu'il soit réellement envoyé.
        logger.info(
            "[SIMULATION E-MAIL -- RESEND_API_KEY non configurée]\n"
            f"À : {destinataire}\nSujet : {sujet}\n--- Corps ---\n{corps_html}\n"
            "--- Fin de simulation : aucun e-mail réellement envoyé ---"
        )
        return True

    try:
        reponse = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {RESEND_API_KEY}"},
            json={
                "from": EMAIL_EXPEDITEUR,
                "to": [destinataire],
                "subject": sujet,
                "html": corps_html,
            },
            timeout=10,
        )
        if reponse.status_code >= 400:
            logger.error(f"Échec d'envoi d'e-mail à {destinataire} : {reponse.status_code} {reponse.text}")
            return False
        return True
    except httpx.HTTPError as e:
        logger.error(f"Erreur réseau lors de l'envoi d'e-mail à {destinataire} : {e}")
        return False


def email_premiere_connexion(destinataire: str, prenom: str, lien_creation_mdp: str) -> bool:
    sujet = "Bienvenue — créez votre mot de passe"
    corps = f"""
    <div style="font-family: Georgia, serif; max-width: 480px; margin: 0 auto; color: #2E2210;">
      <h2 style="color: #B8922A;">Bienvenue {prenom},</h2>
      <p>Votre accès à votre espace de formation personnel a été créé.</p>
      <p>Pour vous connecter pour la première fois, merci de définir votre mot de passe en cliquant sur le lien ci-dessous :</p>
      <p style="text-align: center; margin: 30px 0;">
        <a href="{lien_creation_mdp}" style="background: #2E2210; color: #F5EDD6; padding: 12px 28px; text-decoration: none; border-radius: 6px; font-weight: bold;">
          Créer mon mot de passe
        </a>
      </p>
      <p style="font-size: 13px; color: #9B968A;">Ce lien est valable 48 heures. Si vous n'êtes pas à l'origine de cette demande, vous pouvez ignorer cet e-mail.</p>
    </div>
    """
    return envoyer_email(destinataire, sujet, corps)


def email_reinitialisation_mot_de_passe(destinataire: str, prenom: str, lien_reinitialisation: str) -> bool:
    sujet = "Réinitialisation de votre mot de passe"
    corps = f"""
    <div style="font-family: Georgia, serif; max-width: 480px; margin: 0 auto; color: #2E2210;">
      <h2 style="color: #B8922A;">Bonjour {prenom},</h2>
      <p>Vous avez demandé à réinitialiser votre mot de passe.</p>
      <p style="text-align: center; margin: 30px 0;">
        <a href="{lien_reinitialisation}" style="background: #2E2210; color: #F5EDD6; padding: 12px 28px; text-decoration: none; border-radius: 6px; font-weight: bold;">
          Réinitialiser mon mot de passe
        </a>
      </p>
      <p style="font-size: 13px; color: #9B968A;">Ce lien est valable 48 heures. Si vous n'êtes pas à l'origine de cette demande, vous pouvez ignorer cet e-mail sans risque -- votre mot de passe actuel reste valide.</p>
    </div>
    """
    return envoyer_email(destinataire, sujet, corps)
