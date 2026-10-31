"""
Espace Live — visioconférence LiveKit.

Routes publiques (nécessitent uniquement un token d'annulation valide) :
  GET  /live/rejoindre/{token_annulation}   → page participant (salle d'attente puis salle)
  GET  /live/formateur/{token_annulation}   → interface Laurence (formateur)

Route admin :
  GET  /admin/live/{reservation_id}         → redirection vers /live/formateur/{token}

Route élève connectée :
  GET  /eleve/live                          → hub de la plateforme Live

Route API :
  GET  /api/live/token/{token_annulation}   → retourne un token JWT LiveKit pour le participant
"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from ..database import obtenir_session
from ..models import Reservation
from ..livekit_utils import (
    generer_token_participant,
    generer_token_formateur,
    livekit_actif,
    LIVEKIT_URL,
)
from ..routes.auth import eleve_connecte, admin_connecte
from ..models import Eleve

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


# ---------------------------------------------------------------------------
# Page hub /eleve/live  (accès élève connectée)
# ---------------------------------------------------------------------------

@router.get("/eleve/live", response_class=HTMLResponse)
def page_hub_live(
    request: Request,
    eleve: Eleve = Depends(eleve_connecte),
    session: Session = Depends(obtenir_session),
):
    """Hub 'Ma plateforme Live' — liste les prochaines séances visio de l'élève."""
    maintenant = datetime.utcnow()
    dans_une_semaine = maintenant + timedelta(days=7)

    # On inclut toutes les réservations visio : avec LiveKit (livekit_room_name renseigné)
    # ET sans LiveKit (lien_visio_unique renseigné mais pas de salle LiveKit — créées avant
    # l'activation de LiveKit ou avec un lien externe Whereby/Jitsi).
    from ..models import Lieu
    reservations_live = (
        session.query(Reservation)
        .join(Reservation.lieu)
        .filter(
            Reservation.email == eleve.email,
            Reservation.statut == "en_attente",
            Lieu.type_lieu == "visio",
            Reservation.date_debut >= maintenant - timedelta(hours=1),
            Reservation.date_debut <= dans_une_semaine,
        )
        .order_by(Reservation.date_debut)
        .all()
    )

    from ..pages import _profil_pour_affichage
    from ..config import URL_SITE_VITRINE

    return templates.TemplateResponse(
        request, "eleve/live_hub.html",
        {
            "eleve": eleve,
            "reservations_live": reservations_live,
            "profil": _profil_pour_affichage(session),
            "url_site_vitrine": URL_SITE_VITRINE,
            "livekit_actif": livekit_actif(),
            "maintenant": maintenant,
        },
    )


# ---------------------------------------------------------------------------
# Page participant  /live/rejoindre/{token_annulation}
# ---------------------------------------------------------------------------

@router.get("/live/rejoindre/{token_annulation}", response_class=HTMLResponse)
def page_participant_live(
    request: Request, token_annulation: str,
    session: Session = Depends(obtenir_session),
):
    resa = session.query(Reservation).filter_by(token_annulation=token_annulation).first()
    if resa is None:
        raise HTTPException(status_code=404, detail="Lien de séance introuvable.")
    if resa.statut == "annulee":
        raise HTTPException(status_code=410, detail="Cette séance a été annulée.")
    if not resa.livekit_room_name:
        raise HTTPException(status_code=410, detail="La salle visio n'a pas encore été créée pour cette séance.")

    return templates.TemplateResponse(
        request, "eleve/live_participant.html",
        {
            "reservation": resa,
            "token_annulation": token_annulation,
            "livekit_url": LIVEKIT_URL,
            "livekit_actif": livekit_actif(),
        },
    )


# ---------------------------------------------------------------------------
# API token participant (appelée en JS depuis la page participant)
# ---------------------------------------------------------------------------

DELAI_ACCES_AVANT_RDV_MINUTES = 15  # accès autorisé X minutes avant le début


@router.get("/api/live/token/{token_annulation}")
def api_token_participant(token_annulation: str, session: Session = Depends(obtenir_session)):
    resa = session.query(Reservation).filter_by(token_annulation=token_annulation).first()
    if resa is None:
        raise HTTPException(status_code=404, detail="Réservation introuvable.")
    if not resa.livekit_room_name:
        raise HTTPException(status_code=400, detail="Salle LiveKit non définie.")

    # Vérification de la fenêtre d'accès : autorisé seulement à partir de
    # DELAI_ACCES_AVANT_RDV_MINUTES minutes avant le début.
    maintenant = datetime.utcnow()
    ouverture = resa.date_debut - timedelta(minutes=DELAI_ACCES_AVANT_RDV_MINUTES)
    if maintenant < ouverture:
        # Formater la date en français pour le message
        date_rdv = resa.date_debut
        jours_fr = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
        mois_fr = ["janvier", "février", "mars", "avril", "mai", "juin",
                   "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
        label_date = (
            f"{jours_fr[date_rdv.weekday()]} {date_rdv.day} "
            f"{mois_fr[date_rdv.month - 1]} à {date_rdv.strftime('%H:%M')}"
        )
        raise HTTPException(
            status_code=425,
            detail=f"La salle n'est pas encore ouverte. Votre rendez-vous est le {label_date}. "
                   f"Vous pourrez rejoindre la salle {DELAI_ACCES_AVANT_RDV_MINUTES} minutes avant.",
        )

    # Identité unique : email + id pour éviter les conflits si plusieurs
    # tentatives de connexion
    identite = f"{resa.email}-{resa.id}"
    token = generer_token_participant(resa.livekit_room_name, identite, resa.prenom)
    if token is None:
        raise HTTPException(status_code=503, detail="LiveKit non configuré.")

    return {
        "token": token,
        "room_name": resa.livekit_room_name,
        "livekit_url": LIVEKIT_URL,
        "prenom": resa.prenom,
    }


# ---------------------------------------------------------------------------
# Page formateur  /live/formateur/{token_annulation}
# (accessible aussi depuis /admin/live/{id})
# ---------------------------------------------------------------------------

@router.get("/live/formateur/{token_annulation}", response_class=HTMLResponse)
def page_formateur_live(
    request: Request, token_annulation: str,
    session: Session = Depends(obtenir_session),
):
    """Page formateur — nécessite d'être admin (vérifié via session cookie)."""
    # Vérification de la session admin (sans dependency pour pouvoir retourner un redirect)
    admin_id = request.session.get("admin_id")
    if admin_id is None:
        request.session["apres_connexion_admin"] = f"/live/formateur/{token_annulation}"
        return RedirectResponse(url="/admin/connexion", status_code=303)

    resa = session.query(Reservation).filter_by(token_annulation=token_annulation).first()
    if resa is None:
        raise HTTPException(status_code=404, detail="Réservation introuvable.")
    if not resa.livekit_room_name:
        raise HTTPException(status_code=410, detail="Salle LiveKit non définie pour cette réservation.")

    # Régénérer un token formateur frais (valide 4h) à chaque accès
    token_formateur = generer_token_formateur(resa.livekit_room_name)

    return templates.TemplateResponse(
        request, "admin/live_formateur.html",
        {
            "reservation": resa,
            "token_formateur": token_formateur,
            "livekit_url": LIVEKIT_URL,
            "livekit_actif": livekit_actif(),
        },
    )


@router.get("/admin/live/{reservation_id}", response_class=HTMLResponse)
def page_admin_live_redirect(
    request: Request, reservation_id: int,
    session: Session = Depends(obtenir_session),
):
    """Raccourci admin : redirige vers /live/formateur/{token}."""
    admin_id = request.session.get("admin_id")
    if admin_id is None:
        return RedirectResponse(url="/admin/connexion", status_code=303)

    resa = session.get(Reservation, reservation_id)
    if resa is None:
        raise HTTPException(status_code=404, detail="Réservation introuvable.")

    return RedirectResponse(url=f"/live/formateur/{resa.token_annulation}", status_code=303)
