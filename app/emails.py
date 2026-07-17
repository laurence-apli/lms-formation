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
        "reply_to": [EMAIL_EXPEDITEUR],
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

          <tr>
            <td style="background:linear-gradient(90deg, #B8922A, #C47B6E); height:4px;"></td>
          </tr>

          <tr>
            <td style="padding:40px 40px 32px;">
              <p style="margin:0 0 20px; font-size:17px; color:#2E2210; line-height:1.6;">
                Bonjour {prenom},
              </p>
              <p style="margin:0 0 20px; font-size:15px; color:#3a2f1a; line-height:1.7;">
                Vous avez demandé à réinitialiser votre mot de passe pour accéder à votre espace de formation.
              </p>
              <p style="margin:0 0 32px; font-size:15px; color:#3a2f1a; line-height:1.7;">
                Cliquez sur le bouton ci-dessous pour choisir un nouveau mot de passe. Ce lien est valable <strong>24 heures</strong>.
              </p>

              <table width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td align="center">
                    <a href="{lien}"
                       style="display:inline-block; background:#B8922A; color:#FFFFFF; text-decoration:none;
                              font-family:Arial, sans-serif; font-size:14px; font-weight:700;
                              letter-spacing:1px; text-transform:uppercase;
                              padding:14px 36px; border-radius:8px;">
                      Réinitialiser mon mot de passe
                    </a>
                  </td>
                </tr>
              </table>

              <p style="margin:28px 0 0; font-size:12px; color:#8a7656; line-height:1.6; text-align:center;">
                Si le bouton ne fonctionne pas, copiez ce lien dans votre navigateur :<br>
                <a href="{lien}" style="color:#B8922A; word-break:break-all;">{lien}</a>
              </p>
            </td>
          </tr>

          <tr>
            <td style="padding:0 40px;">
              <hr style="border:none; border-top:1px solid #EDE4D4; margin:0;">
            </td>
          </tr>

          <tr>
            <td style="padding:24px 40px; text-align:center;">
              <p style="margin:0; font-size:12px; color:#8a7656; line-height:1.6;">
                Si vous n'avez pas demandé cette réinitialisation, ignorez simplement cet email.<br>
                Votre mot de passe actuel reste inchangé.
              </p>
              <p style="margin:12px 0 0; font-size:11px; color:#ad9c7a;">
                Laurence Mermet-Bijon · 31 route de Maclas, Véranne (42520)
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""
    return _envoyer_email(destinataire, sujet, corps_html)

EMAIL_ADMIN = os.environ.get("EMAIL_ADMIN", "laurencemb42@gmail.com")

def _corps_email_admin(titre, couleur_barre, montant, nom_complet, email_client, description_achat, motif=""):
    montant_str = "{:.2f}".format(montant)
    motif_html = ""
    if motif:
        motif_html = '<p style="margin:0 0 16px; font-size:15px; color:#2E2210;"><strong>Motif :</strong> ' + motif + '</p>'
    html = '<!DOCTYPE html><html lang="fr"><body style="margin:0; padding:0; background:#F5EDD6; font-family:Georgia, serif;"><table width="100%" cellpadding="0" cellspacing="0" style="background:#F5EDD6; padding:40px 20px;"><tr><td align="center"><table width="560" cellpadding="0" cellspacing="0" style="background:#FFFFFF; border-radius:12px; overflow:hidden;"><tr><td style="background:#2E2210; padding:24px 32px; text-align:center;"><p style="margin:0; font-family:Georgia, serif; font-size:19px; font-weight:600; color:#F5EDD6;">' + titre + '</p></td></tr><tr><td style="background:' + couleur_barre + '; height:4px;"></td></tr>' + '<tr><td style="padding:32px;"><p style="margin:0 0 16px; font-size:15px; color:#2E2210;"><strong>Montant :</strong> ' + montant_str + ' EUR</p><p style="margin:0 0 16px; font-size:15px; color:#2E2210;"><strong>Client :</strong> ' + nom_complet + ' (' + email_client + ')</p><p style="margin:0 0 16px; font-size:15px; color:#2E2210;"><strong>Formation(s) :</strong> ' + description_achat + '</p>' + motif_html + '</td></tr>' + '</table></td></tr></table></body></html>'
    return html

def email_notification_paiement_reussi(nom_complet, email_client, description_achat, montant):
    sujet = "Paiement recu - " + "{:.2f}".format(montant) + " EUR"
    corps_html = _corps_email_admin("Paiement confirme", "#B8922A", montant, nom_complet, email_client, description_achat)
    return _envoyer_email(EMAIL_ADMIN, sujet, corps_html)

def email_notification_paiement_echoue(nom_complet, email_client, description_achat, montant, motif=""):
    sujet = "Paiement echoue - " + "{:.2f}".format(montant) + " EUR"
    corps_html = _corps_email_admin("Tentative de paiement echouee", "#C47B6E", montant, nom_complet, email_client, description_achat, motif)
    return _envoyer_email(EMAIL_ADMIN, sujet, corps_html)
