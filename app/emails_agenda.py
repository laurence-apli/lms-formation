"""
Emails spécifiques à l'agenda natif :
- Confirmation de réservation (avec pièce jointe .ics)
- Rappels J-7 et J-1
- Suivi post-séance (lien Google Avis)
- Notification admin à chaque nouvelle réservation

Le .ics suit la norme iCalendar (RFC 5545).
Pour les séances visio, le lien de connexion est intégré directement
dans l'événement calendrier (champ DESCRIPTION et URL).
"""
import os
import json
import base64
import logging
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
EMAIL_EXPEDITEUR = os.environ.get("EMAIL_EXPEDITEUR", "onboarding@resend.dev")
NOM_EXPEDITEUR = os.environ.get("NOM_EXPEDITEUR", "Laurence Mermet-Bijon")
EMAIL_ADMIN = os.environ.get("EMAIL_ADMIN", "laurencemb42@gmail.com")
URL_PLATEFORME = os.environ.get("URL_PLATEFORME", "https://lms-formation.onrender.com")
LIEN_AVIS_GOOGLE = os.environ.get("LIEN_AVIS_GOOGLE", "https://g.page/r/")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _formater_date_fr(dt: datetime) -> str:
    """'Mardi 12 novembre 2026 à 14h30'"""
    JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
    MOIS = ["", "janvier", "février", "mars", "avril", "mai", "juin",
            "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
    return f"{JOURS[dt.weekday()]} {dt.day} {MOIS[dt.month]} {dt.year} à {dt.strftime('%Hh%M').replace('h00', 'h')}"


def _dt_ics(dt: datetime) -> str:
    """Format iCalendar UTC : 20261112T133000Z"""
    return dt.strftime("%Y%m%dT%H%M%SZ")


def _generer_ics(reservation, type_seance, lieu) -> bytes:
    """
    Génère un fichier .ics (iCalendar RFC 5545) pour un rendez-vous.
    Le lien visio est intégré dans DESCRIPTION et URL si c'est une séance visio.
    """
    uid = f"rdv-{reservation.id}-{reservation.token_annulation[:8]}@laurence-mermet-bijon.fr"
    now_ics = _dt_ics(datetime.utcnow())
    debut_ics = _dt_ics(reservation.date_debut)
    fin_ics = _dt_ics(reservation.date_fin)

    titre = f"Séance avec Laurence Mermet-Bijon"
    if type_seance:
        titre = f"{type_seance.nom} — Laurence Mermet-Bijon"

    # Lieu / adresse pour le champ LOCATION
    location = ""
    if lieu:
        if lieu.type_lieu == "visio":
            location = "Séance en visio"
        elif lieu.adresse:
            location = lieu.adresse.replace("\n", "\\n")
        else:
            location = lieu.nom

    # Description : texte + lien visio si disponible
    desc_lines = [
        f"Rendez-vous avec Laurence Mermet-Bijon.",
        "",
    ]
    if type_seance and type_seance.duree_minutes:
        desc_lines.append(f"Durée : {type_seance.duree_minutes} minutes.")

    if reservation.lien_visio_unique:
        desc_lines += [
            "",
            "🎥 Rejoindre la séance en visio :",
            reservation.lien_visio_unique,
        ]

    lien_annulation = f"{URL_PLATEFORME}/rendez-vous/annuler/{reservation.token_annulation}"
    desc_lines += [
        "",
        "Pour annuler (jusqu'à 24h avant) :",
        lien_annulation,
    ]
    description = "\\n".join(desc_lines)

    # URL principale de l'événement : lien visio si dispo, sinon lien d'annulation
    url_event = reservation.lien_visio_unique or lien_annulation

    # Construire le contenu .ics
    # Note : les lignes de plus de 75 caractères sont repliées avec un espace (line folding RFC 5545)
    def fold(line: str) -> str:
        """Replie les lignes longues selon RFC 5545 (max 75 chars)."""
        if len(line.encode("utf-8")) <= 75:
            return line
        chunks = []
        current = ""
        for char in line:
            if len((current + char).encode("utf-8")) > 75:
                chunks.append(current)
                current = " " + char
            else:
                current += char
        if current:
            chunks.append(current)
        return "\r\n".join(chunks)

    lignes = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Laurence Mermet-Bijon//LMS//FR",
        "CALSCALE:GREGORIAN",
        "METHOD:REQUEST",
        "BEGIN:VEVENT",
        fold(f"UID:{uid}"),
        f"DTSTAMP:{now_ics}",
        f"DTSTART:{debut_ics}",
        f"DTEND:{fin_ics}",
        fold(f"SUMMARY:{titre}"),
        fold(f"LOCATION:{location}"),
        fold(f"DESCRIPTION:{description}"),
        fold(f"URL:{url_event}"),
        "STATUS:CONFIRMED",
        "SEQUENCE:0",
        "BEGIN:VALARM",
        "ACTION:DISPLAY",
        "DESCRIPTION:Rappel séance",
        "TRIGGER:-PT60M",
        "END:VALARM",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    return "\r\n".join(lignes).encode("utf-8")


def _envoyer_avec_ics(
    destinataire: str,
    sujet: str,
    corps_html: str,
    ics_bytes: bytes,
    nom_fichier: str = "rendez-vous.ics",
) -> bool:
    """Envoie un email via Resend avec pièce jointe .ics."""
    if not RESEND_API_KEY:
        logger.warning("RESEND_API_KEY non configurée — email agenda non envoyé à %s", destinataire)
        return False

    ics_b64 = base64.b64encode(ics_bytes).decode("ascii")

    payload = json.dumps({
        "from": f"{NOM_EXPEDITEUR} <{EMAIL_EXPEDITEUR}>",
        "reply_to": [EMAIL_ADMIN],
        "to": [destinataire],
        "subject": sujet,
        "html": corps_html,
        "attachments": [
            {
                "filename": nom_fichier,
                "content": ics_b64,
                "content_type": "text/calendar; charset=utf-8; method=REQUEST",
            }
        ],
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
            ok = resp.status in (200, 201)
            if ok:
                logger.info("Email agenda+ics envoyé à %s", destinataire)
            else:
                logger.error("Erreur Resend %s pour %s", resp.status, destinataire)
            return ok
    except urllib.error.HTTPError as e:
        corps_err = e.read().decode("utf-8", errors="replace")
        logger.error("Erreur HTTP Resend %s pour %s : %s", e.code, destinataire, corps_err)
        return False
    except Exception as e:
        logger.error("Erreur inattendue email agenda %s : %s", destinataire, e)
        return False


def _envoyer_simple(destinataire: str, sujet: str, corps_html: str) -> bool:
    """Envoie un email simple (sans pièce jointe) via Resend."""
    if not RESEND_API_KEY:
        logger.warning("RESEND_API_KEY non configurée — email non envoyé à %s", destinataire)
        return False

    payload = json.dumps({
        "from": f"{NOM_EXPEDITEUR} <{EMAIL_EXPEDITEUR}>",
        "reply_to": [EMAIL_ADMIN],
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
            return resp.status in (200, 201)
    except Exception as e:
        logger.error("Erreur email simple %s : %s", destinataire, e)
        return False


# ---------------------------------------------------------------------------
# Squelette HTML email (identique au style existant)
# ---------------------------------------------------------------------------

def _corps_email(contenu_html: str, couleur_barre: str = "#B8922A") -> str:
    return f"""<!DOCTYPE html>
<html lang="fr">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#F5EDD6;font-family:'Georgia',serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#F5EDD6;padding:40px 20px;">
<tr><td align="center">
<table width="560" cellpadding="0" cellspacing="0"
       style="background:#FFFFFF;border-radius:12px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,0.08);">
  <tr>
    <td style="background:#2E2210;padding:28px 40px;text-align:center;">
      <p style="margin:0;font-family:Georgia,serif;font-size:22px;font-weight:600;color:#F5EDD6;letter-spacing:0.5px;">
        Laurence Mermet-Bijon
      </p>
      <p style="margin:6px 0 0;font-family:Arial,sans-serif;font-size:11px;font-weight:600;
                letter-spacing:3px;color:#B8922A;text-transform:uppercase;">
        Accompagnement féminin
      </p>
    </td>
  </tr>
  <tr><td style="background:linear-gradient(90deg,{couleur_barre},{couleur_barre}cc);height:4px;"></td></tr>
  <tr><td style="padding:40px 40px 32px;">{contenu_html}</td></tr>
  <tr>
    <td style="padding:0 40px;">
      <hr style="border:none;border-top:1px solid #EDE4D4;margin:0;">
    </td>
  </tr>
  <tr>
    <td style="padding:24px 40px;text-align:center;">
      <p style="margin:0;font-size:11px;color:#ad9c7a;">
        Laurence Mermet-Bijon · 31 route de Maclas, Véranne (42520)<br>
        laurencemb42@gmail.com · Ce message est automatique.
      </p>
    </td>
  </tr>
</table>
</td></tr>
</table>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Email 1 : Confirmation de réservation
# ---------------------------------------------------------------------------

def _lien_google_agenda(reservation, type_seance, lieu) -> str:
    """Génère un lien 'Ajouter à Google Agenda' pré-rempli."""
    import urllib.parse
    titre = type_seance.nom if type_seance else "Rendez-vous"
    titre_encode = urllib.parse.quote(f"{titre} — Laurence Mermet-Bijon")
    # Format Google : YYYYMMDDTHHmmssZ
    debut = reservation.date_debut.strftime("%Y%m%dT%H%M%SZ")
    fin = reservation.date_fin.strftime("%Y%m%dT%H%M%SZ") if reservation.date_fin else debut
    if lieu and lieu.type_lieu == "visio":
        location = urllib.parse.quote("Séance en visio")
    elif lieu and lieu.adresse:
        location = urllib.parse.quote(lieu.adresse)
    elif lieu:
        location = urllib.parse.quote(lieu.nom)
    else:
        location = ""
    lien_annulation = f"{URL_PLATEFORME}/rendez-vous/annuler/{reservation.token_annulation}"
    details = urllib.parse.quote(lien_annulation)
    return (
        f"https://calendar.google.com/calendar/render?action=TEMPLATE"
        f"&text={titre_encode}"
        f"&dates={debut}/{fin}"
        f"&location={location}"
        f"&details={details}"
    )


def email_confirmation_reservation(destinataire: str, prenom: str, reservation, type_seance, lieu) -> bool:
    """
    Email envoyé immédiatement après la réservation, avec le fichier .ics en pièce jointe.
    Pour les séances visio, le lien de connexion est dans le .ics ET dans le corps du mail.
    """
    date_fr = _formater_date_fr(reservation.date_debut)
    duree = f"{type_seance.duree_minutes} min" if type_seance else ""
    lieu_label = "En visio" if (lieu and lieu.type_lieu == "visio") else (lieu.nom if lieu else "À définir")

    # Bloc visio (affiché seulement pour les séances en visio)
    bloc_visio = ""
    if reservation.lien_visio_unique:
        bloc_visio = f"""
      <div style="background:#EEF4F8;border-left:4px solid #4A90C4;border-radius:6px;
                  padding:16px 20px;margin:20px 0;">
        <p style="margin:0 0 8px;font-family:Arial,sans-serif;font-size:12px;font-weight:700;
                  letter-spacing:1px;text-transform:uppercase;color:#4A90C4;">Lien de connexion visio</p>
        <p style="margin:0 0 8px;font-size:14px;color:#2E2210;line-height:1.6;">
          Ce lien est <strong>inclus dans votre calendrier</strong> (fichier .ics ci-joint).
          Vous pouvez aussi y accéder directement :
        </p>
        <a href="{reservation.lien_visio_unique}"
           style="display:inline-block;background:#4A90C4;color:#FFFFFF;text-decoration:none;
                  font-family:Arial,sans-serif;font-size:13px;font-weight:700;
                  padding:10px 20px;border-radius:6px;">
          Rejoindre la séance
        </a>
      </div>"""

    lien_annulation = f"{URL_PLATEFORME}/rendez-vous/annuler/{reservation.token_annulation}"
    lien_google = _lien_google_agenda(reservation, type_seance, lieu)

    contenu = f"""
      <p style="margin:0 0 20px;font-size:17px;color:#2E2210;line-height:1.6;">
        Bonjour {prenom},
      </p>
      <p style="margin:0 0 20px;font-size:15px;color:#3a2f1a;line-height:1.7;">
        Votre rendez-vous est confirmé. Vous trouverez ci-joint le fichier <strong>.ics</strong>
        à ajouter à votre calendrier (Apple Calendar, Outlook…).
      </p>

      <div style="background:#FAF5E8;border:1px solid #E8DFC8;border-radius:8px;padding:20px 24px;margin:20px 0;">
        <p style="margin:0 0 10px;font-size:13px;font-weight:700;font-family:Arial,sans-serif;
                  letter-spacing:1px;text-transform:uppercase;color:#B8922A;">Récapitulatif</p>
        <table style="width:100%;border-collapse:collapse;">
          <tr>
            <td style="padding:6px 0;color:#7A6A56;font-size:13px;width:120px;">Séance</td>
            <td style="padding:6px 0;color:#2E2210;font-size:14px;font-weight:600;">
              {type_seance.nom if type_seance else 'Rendez-vous'}
            </td>
          </tr>
          <tr>
            <td style="padding:6px 0;color:#7A6A56;font-size:13px;">Date</td>
            <td style="padding:6px 0;color:#2E2210;font-size:14px;">{date_fr}</td>
          </tr>
          <tr>
            <td style="padding:6px 0;color:#7A6A56;font-size:13px;">Durée</td>
            <td style="padding:6px 0;color:#2E2210;font-size:14px;">{duree}</td>
          </tr>
          <tr>
            <td style="padding:6px 0;color:#7A6A56;font-size:13px;">Lieu</td>
            <td style="padding:6px 0;color:#2E2210;font-size:14px;">{lieu_label}</td>
          </tr>
        </table>
      </div>

      {bloc_visio}

      <div style="margin:24px 0;text-align:center;">
        <a href="{lien_google}"
           style="display:inline-block;background:#4285F4;color:#FFFFFF;text-decoration:none;
                  font-family:Arial,sans-serif;font-size:13px;font-weight:700;
                  padding:11px 22px;border-radius:6px;margin-bottom:8px;">
          📅 Ajouter à Google Agenda
        </a>
        <p style="margin:8px 0 0;font-size:12px;color:#7A6A56;">
          Apple Calendar / Outlook : ouvrez le fichier <strong>.ics</strong> en pièce jointe.
        </p>
      </div>

      <p style="margin:20px 0 8px;font-size:13px;color:#7A6A56;line-height:1.6;">
        Pour annuler (possible jusqu'à 24h avant la séance) :
      </p>
      <p style="margin:0;font-size:13px;">
        <a href="{lien_annulation}" style="color:#B8922A;">{lien_annulation}</a>
      </p>
    """

    corps_html = _corps_email(contenu)
    ics_bytes = _generer_ics(reservation, type_seance, lieu)

    return _envoyer_avec_ics(
        destinataire=destinataire,
        sujet=f"Confirmation — {type_seance.nom if type_seance else 'Rendez-vous'} le {_formater_date_fr(reservation.date_debut)}",
        corps_html=corps_html,
        ics_bytes=ics_bytes,
        nom_fichier="rendez-vous-laurence-mermet-bijon.ics",
    )


# ---------------------------------------------------------------------------
# Email 2 : Rappel J-7 / J-1
# ---------------------------------------------------------------------------

def email_rappel_reservation(reservation, type_seance, lieu, type_rappel: str) -> bool:
    """Rappel J-7 ou J-1 avant la séance."""
    date_fr = _formater_date_fr(reservation.date_debut)
    lieu_label = "en visio" if (lieu and lieu.type_lieu == "visio") else (f"au {lieu.nom}" if lieu else "")
    label_rappel = "dans 7 jours" if type_rappel == "j7" else "demain"

    bloc_visio = ""
    if reservation.lien_visio_unique:
        bloc_visio = f"""
      <div style="background:#EEF4F8;border-left:4px solid #4A90C4;border-radius:6px;
                  padding:14px 18px;margin:20px 0;">
        <p style="margin:0 0 8px;font-size:13px;font-weight:700;font-family:Arial,sans-serif;
                  letter-spacing:1px;text-transform:uppercase;color:#4A90C4;">Votre lien de connexion</p>
        <a href="{reservation.lien_visio_unique}"
           style="display:inline-block;background:#4A90C4;color:#FFFFFF;text-decoration:none;
                  font-family:Arial,sans-serif;font-size:13px;font-weight:700;
                  padding:10px 20px;border-radius:6px;">
          Rejoindre la séance
        </a>
      </div>"""

    contenu = f"""
      <p style="margin:0 0 20px;font-size:17px;color:#2E2210;line-height:1.6;">
        Bonjour {reservation.prenom},
      </p>
      <p style="margin:0 0 20px;font-size:15px;color:#3a2f1a;line-height:1.7;">
        Un rappel pour votre séance <strong>{label_rappel}</strong> {lieu_label} :
      </p>

      <div style="background:#FAF5E8;border:1px solid #E8DFC8;border-radius:8px;padding:16px 20px;margin:20px 0;">
        <p style="margin:0;font-size:15px;color:#2E2210;font-weight:600;">{date_fr}</p>
        <p style="margin:6px 0 0;font-size:13px;color:#7A6A56;">
          {type_seance.nom if type_seance else 'Rendez-vous'}
          {' · ' + str(type_seance.duree_minutes) + ' min' if type_seance else ''}
        </p>
      </div>

      {bloc_visio}

      <p style="margin:20px 0 0;font-size:12px;color:#8a7656;">
        À bientôt,<br><em>Laurence</em>
      </p>
    """

    return _envoyer_simple(
        destinataire=reservation.email,
        sujet=f"Rappel — votre séance {label_rappel} {'(visio)' if reservation.lien_visio_unique else ''}",
        corps_html=_corps_email(contenu),
    )


# ---------------------------------------------------------------------------
# Email 3 : Suivi post-séance
# ---------------------------------------------------------------------------

def email_suivi_post_seance(reservation) -> bool:
    """Email envoyé 24h après la séance avec un lien vers les avis Google."""
    contenu = f"""
      <p style="margin:0 0 20px;font-size:17px;color:#2E2210;line-height:1.6;">
        Bonjour {reservation.prenom},
      </p>
      <p style="margin:0 0 20px;font-size:15px;color:#3a2f1a;line-height:1.7;">
        J'espère que notre séance vous a été utile. Si vous souhaitez partager votre expérience,
        un avis Google m'aide beaucoup à me faire connaître — cela ne prend que quelques secondes.
      </p>
      <table width="100%" cellpadding="0" cellspacing="0">
        <tr><td align="center">
          <a href="{LIEN_AVIS_GOOGLE}"
             style="display:inline-block;background:#B8922A;color:#FFFFFF;text-decoration:none;
                    font-family:Arial,sans-serif;font-size:14px;font-weight:700;
                    letter-spacing:1px;text-transform:uppercase;
                    padding:14px 32px;border-radius:8px;">
            Laisser un avis
          </a>
        </td></tr>
      </table>
      <p style="margin:28px 0 0;font-size:14px;color:#3a2f1a;line-height:1.7;">
        Merci pour votre confiance, et à bientôt.<br>
        <em>Laurence</em>
      </p>
    """

    return _envoyer_simple(
        destinataire=reservation.email,
        sujet="Merci pour votre séance — votre avis compte",
        corps_html=_corps_email(contenu),
    )


# ---------------------------------------------------------------------------
# Email 4 : Notification admin nouvelle réservation
# ---------------------------------------------------------------------------

def email_admin_nouvelle_reservation(reservation, type_seance, lieu) -> bool:
    """Notifie Laurence dès qu'une cliente prend rendez-vous."""
    date_fr = _formater_date_fr(reservation.date_debut)
    lieu_label = lieu.nom if lieu else "—"
    contenu = f"""
      <p style="margin:0 0 16px;font-size:15px;color:#2E2210;">
        <strong>{reservation.prenom} {reservation.nom}</strong>
        ({reservation.email}) vient de prendre rendez-vous.
      </p>
      <table style="width:100%;border-collapse:collapse;background:#FAF5E8;
                    border-radius:8px;border:1px solid #E8DFC8;">
        <tr><td style="padding:8px 14px;color:#7A6A56;font-size:13px;width:120px;">Séance</td>
            <td style="padding:8px 14px;color:#2E2210;font-weight:600;">
              {type_seance.nom if type_seance else '—'}
            </td></tr>
        <tr><td style="padding:8px 14px;color:#7A6A56;font-size:13px;">Date</td>
            <td style="padding:8px 14px;color:#2E2210;">{date_fr}</td></tr>
        <tr><td style="padding:8px 14px;color:#7A6A56;font-size:13px;">Lieu</td>
            <td style="padding:8px 14px;color:#2E2210;">{lieu_label}</td></tr>
        <tr><td style="padding:8px 14px;color:#7A6A56;font-size:13px;">Téléphone</td>
            <td style="padding:8px 14px;color:#2E2210;">{reservation.telephone or '—'}</td></tr>
        <tr><td style="padding:8px 14px;color:#7A6A56;font-size:13px;">Message</td>
            <td style="padding:8px 14px;color:#2E2210;">{reservation.message or '—'}</td></tr>
      </table>
      <p style="margin:16px 0 0;font-size:12px;color:#8a7656;">
        Gérer via l'admin : {URL_PLATEFORME}/admin/agenda/
      </p>
    """

    return _envoyer_simple(
        destinataire=EMAIL_ADMIN,
        sujet=f"Nouveau RDV — {reservation.prenom} {reservation.nom} le {reservation.date_debut.strftime('%d/%m %Hh%M')}",
        corps_html=_corps_email(contenu, couleur_barre="#3B8C5A"),
    )
