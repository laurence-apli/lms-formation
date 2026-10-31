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
    expulser_participant,
    muter_participant_serveur,
    lister_participants,
    terminer_salle,
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
            "room_name": resa.livekit_room_name,
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


# ---------------------------------------------------------------------------
# API admin : actions sur la salle LiveKit (expulsion, mute serveur, fin séance)
# ---------------------------------------------------------------------------

def _verifier_admin(request: Request):
    """Vérifie que la session admin est active, lève 401 sinon."""
    if not request.session.get("admin_id"):
        raise HTTPException(status_code=401, detail="Non autorisé.")


@router.post("/api/admin/live/{room_name}/kick/{identity}")
def api_kick_participant(
    room_name: str, identity: str, request: Request,
    session: Session = Depends(obtenir_session),
):
    """Expulse un participant de la salle LiveKit côté serveur."""
    _verifier_admin(request)
    if not livekit_actif():
        raise HTTPException(status_code=503, detail="LiveKit non configuré.")

    ok = expulser_participant(room_name, identity)
    if not ok:
        raise HTTPException(status_code=500, detail="Impossible d'expulser le participant.")
    return {"ok": True, "identity": identity}


@router.post("/api/admin/live/{room_name}/mute/{identity}")
async def api_mute_participant(
    room_name: str, identity: str, request: Request,
    session: Session = Depends(obtenir_session),
):
    """
    Coupe le micro d'un participant côté serveur LiveKit.
    Corps JSON attendu : { "muted": true|false }
    """
    _verifier_admin(request)
    if not livekit_actif():
        raise HTTPException(status_code=503, detail="LiveKit non configuré.")

    body = await request.json()
    muted = body.get("muted", True)

    # Récupérer le track_sid audio du participant
    participants = lister_participants(room_name)
    track_sid = None
    for p in participants:
        if p.get("identity") == identity:
            for track in p.get("tracks", []):
                if track.get("type") == 0:  # 0 = AUDIO dans le proto LiveKit
                    track_sid = track.get("sid")
                    break
            break

    if not track_sid:
        # Pas de piste audio trouvée — le participant n'est peut-être pas encore connecté
        raise HTTPException(status_code=404, detail="Piste audio introuvable pour ce participant.")

    ok = muter_participant_serveur(room_name, identity, track_sid, muted)
    if not ok:
        raise HTTPException(status_code=500, detail="Impossible de modifier le micro.")
    return {"ok": True, "identity": identity, "muted": muted}


@router.post("/api/admin/live/{room_name}/end")
def api_terminer_seance(
    room_name: str, request: Request,
    session: Session = Depends(obtenir_session),
):
    """Ferme la salle LiveKit et expulse tous les participants côté serveur."""
    _verifier_admin(request)
    if not livekit_actif():
        raise HTTPException(status_code=503, detail="LiveKit non configuré.")

    ok = terminer_salle(room_name)
    # On ne lève pas d'erreur si la salle était déjà vide/inexistante
    return {"ok": ok, "room": room_name}
