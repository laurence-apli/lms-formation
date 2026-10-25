"""
Routes de l'agenda natif — remplace Resalib (70€/mois).
Couvre :
  - Admin : paramétrage (types de séances, lieux, plages dispo) + vue agenda
  - Public : page /rendez-vous (réservation 4 étapes)
  - API : disponibilités, création/annulation de réservation
  - Cron : envoi des rappels J-7, J-1 et suivi post-séance
"""
import json
import os
import secrets
from datetime import datetime, timedelta, date, time
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import obtenir_session
from ..models import (
    TypeSeance, Lieu, PlageDisponibilite, Reservation, RappelEnvoye,
    SeanceAccompagnement, AccesFormation, Eleve, Administrateur,
    IndisponibiliteAgenda,
)
from .auth import admin_connecte

templates = Jinja2Templates(directory="app/templates")

# Filtre Jinja2 : date en français lisible
def _filtre_datefr(dt: datetime) -> str:
    JOURS = ["lundi","mardi","mercredi","jeudi","vendredi","samedi","dimanche"]
    MOIS = ["","janvier","février","mars","avril","mai","juin",
            "juillet","août","septembre","octobre","novembre","décembre"]
    if not dt:
        return "—"
    return f"{JOURS[dt.weekday()]} {dt.day} {MOIS[dt.month]} {dt.year} à {dt.strftime('%H').lstrip('0') or '0'}h{dt.strftime('%M') if dt.minute else ''}"

templates.env.filters["datefr"] = _filtre_datefr

# ---------------------------------------------------------------------------
# Routeurs
# ---------------------------------------------------------------------------
admin_router = APIRouter(prefix="/admin/agenda", dependencies=[Depends(admin_connecte)])
public_router = APIRouter()
api_router = APIRouter(prefix="/api/agenda")
cron_router = APIRouter(prefix="/cron")
webhook_router = APIRouter()  # webhook Stripe agenda : /webhooks/agenda-stripe


# ===========================================================================
# ADMIN — Pages HTML
# ===========================================================================

@admin_router.get("/", response_class=HTMLResponse)
def page_agenda_admin(
    request: Request,
    admin: Administrateur = Depends(admin_connecte),
    session: Session = Depends(obtenir_session),
):
    """Page principale admin : vue semaine + listes latérales."""
    types_seances = session.query(TypeSeance).filter_by(actif=True).order_by(TypeSeance.ordre).all()
    lieux = session.query(Lieu).filter_by(actif=True).all()
    plages = session.query(PlageDisponibilite).filter_by(actif=True).all()

    # Reservations des 4 prochaines semaines (aperçu)
    maintenant = datetime.utcnow()
    dans_4_semaines = maintenant + timedelta(weeks=4)
    reservations = (
        session.query(Reservation)
        .filter(
            Reservation.date_debut >= maintenant,
            Reservation.date_debut <= dans_4_semaines,
            Reservation.statut == "en_attente",
        )
        .order_by(Reservation.date_debut)
        .all()
    )

    profil = {
        "nom": admin.nom, "prenom": admin.prenom, "email": admin.email,
        "telephone": admin.telephone, "photo_url": admin.photo_url,
        "logo_url": admin.logo_url, "lien_github": admin.lien_github,
    }

    return templates.TemplateResponse(
        request,
        "admin/agenda.html",
        {
            "profil": profil,
            "page_active": "agenda",
            "types_seances": types_seances,
            "lieux": lieux,
            "plages": plages,
            "reservations": reservations,
        },
    )


# ---------------------------------------------------------------------------
# ADMIN — API Types de séances
# ---------------------------------------------------------------------------

@admin_router.get("/types-seances")
def lister_types_seances(session: Session = Depends(obtenir_session)):
    ts = session.query(TypeSeance).order_by(TypeSeance.ordre).all()
    return [
        {
            "id": t.id, "nom": t.nom, "duree_minutes": t.duree_minutes,
            "pause_apres_minutes": t.pause_apres_minutes or 0,
            "modalite": t.modalite, "couleur_hex": t.couleur_hex,
            "description": t.description,
            "format_seance": t.format_seance or "individuelle",
            "nb_places_max": t.nb_places_max,
            "actif": t.actif, "ordre": t.ordre,
            "visibilite": t.visibilite or "public",
            "code_acces": t.code_acces or "",
        }
        for t in ts
    ]


class TypeSeanceIn(BaseModel):
    nom: str
    duree_minutes: int = 60
    pause_apres_minutes: int = 0
    modalite: str = "cabinet"
    couleur_hex: str = "#B8922A"
    description: Optional[str] = None   # le JS peut envoyer null si vide
    format_seance: str = "individuelle"  # 'individuelle' | 'collective'
    nb_places_max: Optional[int] = None  # None si individuelle
    prix: Optional[float] = None         # Prix en € (None = gratuit)
    mode_paiement: str = "sans_paiement" # 'sans_paiement' | 'optionnel' | 'obligatoire'
    visibilite: str = "public"           # 'public' | 'lien' | 'admin'
    code_acces: Optional[str] = None     # slug unique pour accès par lien
    actif: bool = True


@admin_router.post("/types-seances")
def creer_type_seance(data: TypeSeanceIn, session: Session = Depends(obtenir_session)):
    if not data.nom.strip():
        raise HTTPException(status_code=400, detail="Le nom est requis.")
    if data.modalite not in ("cabinet", "visio", "les_deux"):
        raise HTTPException(status_code=400, detail="Modalité invalide.")

    max_ordre = session.query(TypeSeance).count()
    ts = TypeSeance(
        nom=data.nom.strip(),
        duree_minutes=data.duree_minutes,
        pause_apres_minutes=data.pause_apres_minutes,
        modalite=data.modalite,
        couleur_hex=data.couleur_hex,
        description=data.description.strip() if data.description else None,
        format_seance=data.format_seance if data.format_seance in ("individuelle", "collective") else "individuelle",
        nb_places_max=data.nb_places_max if data.format_seance == "collective" else None,
        prix=data.prix if data.prix and data.prix > 0 else None,
        mode_paiement=data.mode_paiement if data.mode_paiement in ("sans_paiement", "optionnel", "obligatoire") else "sans_paiement",
        visibilite=data.visibilite if data.visibilite in ("public", "lien", "admin") else "public",
        code_acces=data.code_acces.strip().lower() if data.code_acces else None,
        ordre=max_ordre,
    )
    session.add(ts)
    session.commit()
    return {"id": ts.id, "nom": ts.nom}


@admin_router.put("/types-seances/{ts_id}")
def modifier_type_seance(ts_id: int, data: TypeSeanceIn, session: Session = Depends(obtenir_session)):
    ts = session.get(TypeSeance, ts_id)
    if not ts:
        raise HTTPException(status_code=404, detail="Type de séance introuvable.")
    ts.nom = data.nom.strip()
    ts.duree_minutes = data.duree_minutes
    ts.pause_apres_minutes = data.pause_apres_minutes
    ts.modalite = data.modalite
    ts.couleur_hex = data.couleur_hex
    ts.description = data.description.strip() if data.description else None
    ts.format_seance = data.format_seance if data.format_seance in ("individuelle", "collective") else "individuelle"
    ts.nb_places_max = data.nb_places_max if data.format_seance == "collective" else None
    ts.prix = data.prix if data.prix and data.prix > 0 else None
    ts.mode_paiement = data.mode_paiement if data.mode_paiement in ("sans_paiement", "optionnel", "obligatoire") else "sans_paiement"
    ts.visibilite = data.visibilite if data.visibilite in ("public", "lien", "admin") else "public"
    ts.code_acces = data.code_acces.strip().lower() if data.code_acces else None
    ts.actif = data.actif
    session.commit()
    return {"ok": True}


@admin_router.delete("/types-seances/{ts_id}")
def supprimer_type_seance(ts_id: int, session: Session = Depends(obtenir_session)):
    ts = session.get(TypeSeance, ts_id)
    if not ts:
        raise HTTPException(status_code=404, detail="Type de séance introuvable.")
    nb_reservations = session.query(Reservation).filter_by(type_seance_id=ts_id).count()
    if nb_reservations > 0:
        ts.actif = False
        session.commit()
        return {"ok": True, "archive": True}
    session.delete(ts)
    session.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# ADMIN — API Lieux
# ---------------------------------------------------------------------------

@admin_router.get("/lieux")
def lister_lieux(session: Session = Depends(obtenir_session)):
    lieux = session.query(Lieu).all()
    return [
        {
            "id": l.id, "nom": l.nom, "adresse": l.adresse,
            "type_lieu": l.type_lieu, "lien_visio": l.lien_visio, "actif": l.actif,
        }
        for l in lieux
    ]


class LieuIn(BaseModel):
    nom: str
    adresse: Optional[str] = None
    type_lieu: str = "cabinet"
    lien_visio: Optional[str] = None
    actif: bool = True


@admin_router.post("/lieux")
def creer_lieu(data: LieuIn, session: Session = Depends(obtenir_session)):
    if not data.nom.strip():
        raise HTTPException(status_code=400, detail="Le nom est requis.")
    if data.type_lieu not in ("cabinet", "visio", "autre"):
        raise HTTPException(status_code=400, detail="Type de lieu invalide.")

    lieu = Lieu(
        nom=data.nom.strip(),
        adresse=(data.adresse or "").strip() or None,
        type_lieu=data.type_lieu,
        lien_visio=(data.lien_visio or "").strip() or None,
    )
    session.add(lieu)
    session.commit()
    return {"id": lieu.id, "nom": lieu.nom}


@admin_router.put("/lieux/{lieu_id}")
def modifier_lieu(lieu_id: int, data: LieuIn, session: Session = Depends(obtenir_session)):
    lieu = session.get(Lieu, lieu_id)
    if not lieu:
        raise HTTPException(status_code=404, detail="Lieu introuvable.")
    lieu.nom = data.nom.strip()
    lieu.adresse = (data.adresse or "").strip() or None
    lieu.type_lieu = data.type_lieu
    lieu.lien_visio = (data.lien_visio or "").strip() or None
    lieu.actif = data.actif
    session.commit()
    return {"ok": True}


@admin_router.delete("/lieux/{lieu_id}")
def supprimer_lieu(lieu_id: int, session: Session = Depends(obtenir_session)):
    lieu = session.get(Lieu, lieu_id)
    if not lieu:
        raise HTTPException(status_code=404, detail="Lieu introuvable.")
    nb = session.query(Reservation).filter_by(lieu_id=lieu_id).count()
    if nb > 0:
        lieu.actif = False
        session.commit()
        return {"ok": True, "archive": True}
    session.delete(lieu)
    session.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# ADMIN — API Plages de disponibilité
# ---------------------------------------------------------------------------

@admin_router.get("/plages")
def lister_plages(session: Session = Depends(obtenir_session)):
    plages = session.query(PlageDisponibilite).filter_by(actif=True).all()
    jours = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
    return [
        {
            "id": p.id,
            "type_seance_id": p.type_seance_id,
            "type_seance_nom": p.type_seance.nom if p.type_seance else "",
            "type_seance_couleur": p.type_seance.couleur_hex if p.type_seance else "#B8922A",
            "lieu_id": p.lieu_id,
            "lieu_nom": p.lieu.nom if p.lieu else "",
            "jour_semaine": p.jour_semaine,
            "jour_label": jours[p.jour_semaine] if p.jour_semaine is not None else "Date unique",
            "date_unique": p.date_unique.isoformat() if p.date_unique else None,
            "heure_debut": p.heure_debut,
            "heure_fin": p.heure_fin,
            "pause_debut": p.pause_debut,
            "pause_fin": p.pause_fin,
            "valide_du": p.valide_du.date().isoformat() if p.valide_du else None,
            "valide_au": p.valide_au.date().isoformat() if p.valide_au else None,
        }
        for p in plages
    ]


class PlageIn(BaseModel):
    type_seance_id: int
    lieu_id: int
    heure_debut: str
    heure_fin: str
    jour_semaine: Optional[int] = None
    date_unique: Optional[str] = None
    valide_du: Optional[str] = None   # "YYYY-MM-DD" ou None = toujours valable
    valide_au: Optional[str] = None   # "YYYY-MM-DD" ou None = pas de fin
    actif: bool = True


def _parse_date_opt(s: Optional[str]) -> Optional[datetime]:
    """Convertit une chaîne YYYY-MM-DD en datetime (minuit), ou None si vide."""
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Format de date invalide : {s}")


@admin_router.post("/plages")
def creer_plage(data: PlageIn, session: Session = Depends(obtenir_session)):
    if data.jour_semaine is None and not data.date_unique:
        raise HTTPException(status_code=400, detail="Jour de la semaine ou date unique requis.")

    date_u = _parse_date_opt(data.date_unique)
    valide_du = _parse_date_opt(data.valide_du)
    valide_au = _parse_date_opt(data.valide_au)

    plage = PlageDisponibilite(
        type_seance_id=data.type_seance_id,
        lieu_id=data.lieu_id,
        jour_semaine=data.jour_semaine,
        date_unique=date_u,
        heure_debut=data.heure_debut,
        heure_fin=data.heure_fin,
        valide_du=valide_du,
        valide_au=valide_au,
    )
    session.add(plage)
    session.commit()
    return {"id": plage.id}


@admin_router.put("/plages/{plage_id}")
def modifier_plage(plage_id: int, data: PlageIn, session: Session = Depends(obtenir_session)):
    """Modifie une plage de disponibilité existante."""
    plage = session.get(PlageDisponibilite, plage_id)
    if not plage:
        raise HTTPException(status_code=404, detail="Plage introuvable.")
    if data.jour_semaine is None and not data.date_unique:
        raise HTTPException(status_code=400, detail="Jour de la semaine ou date unique requis.")

    plage.type_seance_id = data.type_seance_id
    plage.lieu_id = data.lieu_id
    plage.jour_semaine = data.jour_semaine
    plage.date_unique = _parse_date_opt(data.date_unique)
    plage.heure_debut = data.heure_debut
    plage.heure_fin = data.heure_fin
    plage.valide_du = _parse_date_opt(data.valide_du)
    plage.valide_au = _parse_date_opt(data.valide_au)
    plage.actif = data.actif
    session.commit()
    return {"ok": True}


@admin_router.delete("/plages/{plage_id}")
def supprimer_plage(plage_id: int, session: Session = Depends(obtenir_session)):
    plage = session.get(PlageDisponibilite, plage_id)
    if not plage:
        raise HTTPException(status_code=404, detail="Plage introuvable.")
    plage.actif = False
    session.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# ADMIN — API Indisponibilités
# ---------------------------------------------------------------------------

@admin_router.get("/indisponibilites")
def lister_indisponibilites(session: Session = Depends(obtenir_session)):
    """Liste toutes les indisponibilités (futures d'abord)."""
    indispos = (
        session.query(IndisponibiliteAgenda)
        .order_by(IndisponibiliteAgenda.date_debut)
        .all()
    )
    return [
        {
            "id": i.id,
            "date_debut": i.date_debut.isoformat(),
            "date_fin": i.date_fin.isoformat(),
            "motif": i.motif,
            "cree_le": i.cree_le.isoformat() if i.cree_le else None,
        }
        for i in indispos
    ]


class IndisponibiliteIn(BaseModel):
    date_debut: str    # ISO datetime "YYYY-MM-DD" ou "YYYY-MM-DDTHH:MM"
    date_fin: str      # ISO datetime (inclusive)
    motif: Optional[str] = None


@admin_router.post("/indisponibilites")
def creer_indisponibilite(data: IndisponibiliteIn, session: Session = Depends(obtenir_session)):
    """Crée une indisponibilité (vacances, jour de repos, etc.)."""
    try:
        dt_debut = datetime.fromisoformat(data.date_debut)
    except ValueError:
        raise HTTPException(status_code=400, detail="Format date_debut invalide.")
    try:
        dt_fin = datetime.fromisoformat(data.date_fin)
    except ValueError:
        raise HTTPException(status_code=400, detail="Format date_fin invalide.")

    if dt_fin < dt_debut:
        raise HTTPException(status_code=400, detail="La date de fin doit être après la date de début.")

    # Si date pure (sans heure), on étend la fin à 23:59 pour couvrir toute la journée
    if dt_fin.hour == 0 and dt_fin.minute == 0 and dt_fin.second == 0:
        dt_fin = dt_fin.replace(hour=23, minute=59)

    indispo = IndisponibiliteAgenda(
        date_debut=dt_debut,
        date_fin=dt_fin,
        motif=(data.motif or "").strip() or None,
    )
    session.add(indispo)
    session.commit()
    return {"id": indispo.id, "ok": True}


@admin_router.delete("/indisponibilites/{indispo_id}")
def supprimer_indisponibilite(indispo_id: int, session: Session = Depends(obtenir_session)):
    """Supprime définitivement une indisponibilité."""
    indispo = session.get(IndisponibiliteAgenda, indispo_id)
    if not indispo:
        raise HTTPException(status_code=404, detail="Indisponibilité introuvable.")
    session.delete(indispo)
    session.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# ADMIN — Gestion des réservations
# ---------------------------------------------------------------------------

@admin_router.get("/reservations")
def lister_reservations(
    semaine: Optional[str] = None,  # ISO date du lundi de la semaine voulue
    session: Session = Depends(obtenir_session),
):
    """Réservations pour une semaine donnée (défaut : semaine courante)."""
    if semaine:
        try:
            debut_semaine = datetime.fromisoformat(semaine)
        except ValueError:
            debut_semaine = datetime.utcnow()
    else:
        aujourd_hui = datetime.utcnow()
        debut_semaine = aujourd_hui - timedelta(days=aujourd_hui.weekday())

    debut_semaine = debut_semaine.replace(hour=0, minute=0, second=0, microsecond=0)
    fin_semaine = debut_semaine + timedelta(days=7)

    reservations = (
        session.query(Reservation)
        .filter(
            Reservation.date_debut >= debut_semaine,
            Reservation.date_debut < fin_semaine,
        )
        .order_by(Reservation.date_debut)
        .all()
    )

    return [_serialiser_reservation(r) for r in reservations]


class StatutIn(BaseModel):
    statut: str
    note_admin: str = ""


@admin_router.post("/reservations/{resa_id}/statut")
def changer_statut_reservation(
    resa_id: int,
    data: StatutIn,
    session: Session = Depends(obtenir_session),
):
    resa = session.get(Reservation, resa_id)
    if not resa:
        raise HTTPException(status_code=404, detail="Réservation introuvable.")
    if data.statut not in ("en_attente", "annulee", "realisee"):
        raise HTTPException(status_code=400, detail="Statut invalide.")

    resa.statut = data.statut
    if data.note_admin:
        resa.note_admin = data.note_admin.strip()

    # Si marquée réalisée, créer une SeanceAccompagnement si l'élève est connu
    if data.statut == "realisee" and resa.eleve_id:
        from ..models import AccesFormation
        # On cherche le premier accès actif de l'élève
        acces = (
            session.query(AccesFormation)
            .filter_by(eleve_id=resa.eleve_id)
            .first()
        )
        if acces:
            # Vérifier qu'il n'existe pas déjà une SeanceAccompagnement pour cette réservation
            existante = (
                session.query(SeanceAccompagnement)
                .filter_by(reservation_id=resa_id)
                .first()
            )
            if not existante:
                modalite = resa.type_seance.modalite if resa.type_seance else "cabinet"
                type_accomp = "visio" if modalite == "visio" else "cabinet"
                seance = SeanceAccompagnement(
                    acces_id=acces.id,
                    date_seance=resa.date_debut,
                    statut="realise",
                    date_realise=datetime.utcnow(),
                    type_accompagnement=type_accomp,
                    reservation_id=resa_id,
                )
                session.add(seance)

    session.commit()
    return {"ok": True}


class NoteIn(BaseModel):
    note: str = ""


@admin_router.post("/reservations/{resa_id}/note")
def sauvegarder_note_reservation(
    resa_id: int,
    data: NoteIn,
    session: Session = Depends(obtenir_session),
):
    """Sauvegarde la note interne d'une réservation (admin)."""
    resa = session.get(Reservation, resa_id)
    if not resa:
        raise HTTPException(status_code=404, detail="Réservation introuvable.")
    resa.note_admin = data.note.strip() or None
    session.commit()
    return {"ok": True}


@admin_router.post("/reservations/creer")
def creer_reservation_admin(
    prenom: str = Form(...),
    nom: str = Form(...),
    email: str = Form(...),
    telephone: str = Form(""),
    type_seance_id: int = Form(...),
    lieu_id: int = Form(...),
    date_debut: str = Form(...),  # ISO datetime
    note_admin: str = Form(""),
    session: Session = Depends(obtenir_session),
):
    """Création manuelle d'une réservation depuis l'admin."""
    try:
        dt_debut = datetime.fromisoformat(date_debut)
    except ValueError:
        raise HTTPException(status_code=400, detail="Format de date invalide.")

    ts = session.get(TypeSeance, type_seance_id)
    if not ts:
        raise HTTPException(status_code=404, detail="Type de séance introuvable.")

    dt_fin = dt_debut + timedelta(minutes=ts.duree_minutes)

    # Lien visio unique si séance visio
    lieu = session.get(Lieu, lieu_id)
    lien_visio = None
    if lieu and lieu.type_lieu == "visio":
        lien_visio = lieu.lien_visio

    # Chercher si l'élève existe en base
    eleve = session.query(Eleve).filter_by(email=email.strip().lower()).first()

    resa = Reservation(
        type_seance_id=type_seance_id,
        lieu_id=lieu_id,
        eleve_id=eleve.id if eleve else None,
        prenom=prenom.strip(),
        nom=nom.strip(),
        email=email.strip().lower(),
        telephone=telephone.strip() or None,
        date_debut=dt_debut,
        date_fin=dt_fin,
        statut="en_attente",
        source="admin",
        lien_visio_unique=lien_visio,
        note_admin=note_admin.strip() or None,
    )
    session.add(resa)
    session.commit()
    return {"id": resa.id, "ok": True}


# ===========================================================================
# API PUBLIQUE — Lectures (appelées par admin JS et page publique)
# Ces routes sont sans auth : elles n'exposent que des données non sensibles.
# ===========================================================================

@api_router.get("/types-seances")
def api_lister_types_seances(
    actif: Optional[int] = None,
    acces: Optional[str] = None,   # code slug pour débloquer les types 'lien'
    admin: Optional[int] = None,   # 1 = mode admin (tous les types, sans filtre visibilité)
    session: Session = Depends(obtenir_session),
):
    """Liste les types de séances.
    - Sans paramètres : types 'public' uniquement.
    - ?acces=CODE : types 'public' + le type 'lien' correspondant au code.
    - ?admin=1 : tous les types (réservé à l'usage admin JS, pas de vérification ici car déjà derrière auth).
    """
    q = session.query(TypeSeance)
    if actif is not None:
        q = q.filter_by(actif=bool(actif))

    ts_all = q.order_by(TypeSeance.ordre).all()

    # Filtrage visibilité côté Python (simple)
    if admin:
        ts = ts_all  # admin : tout voir
    elif acces:
        code = acces.strip().lower()
        ts = [t for t in ts_all if (t.visibilite or "public") == "public"
              or ((t.visibilite or "public") == "lien" and (t.code_acces or "").lower() == code)]
    else:
        ts = [t for t in ts_all if (t.visibilite or "public") == "public"]

    return [
        {
            "id": t.id, "nom": t.nom, "duree_minutes": t.duree_minutes,
            "pause_apres_minutes": t.pause_apres_minutes or 0,
            "modalite": t.modalite, "couleur_hex": t.couleur_hex,
            "description": t.description, "actif": t.actif, "ordre": t.ordre,
            "prix": float(t.prix) if t.prix is not None else None,
            "mode_paiement": t.mode_paiement or "sans_paiement",
            "visibilite": t.visibilite or "public",
        }
        for t in ts
    ]


@api_router.get("/lieux")
def api_lister_lieux(
    actif: Optional[int] = None,
    session: Session = Depends(obtenir_session),
):
    """Liste les lieux (publique + admin JS)."""
    q = session.query(Lieu)
    if actif is not None:
        q = q.filter_by(actif=bool(actif))
    lieux = q.order_by(Lieu.nom).all()
    return [
        {
            "id": l.id, "nom": l.nom, "type_lieu": l.type_lieu,
            "adresse": l.adresse, "actif": l.actif,
        }
        for l in lieux
    ]


@api_router.get("/plages")
def api_lister_plages(
    actif: Optional[int] = None,
    session: Session = Depends(obtenir_session),
):
    """Liste les plages de disponibilité (admin JS)."""
    q = session.query(PlageDisponibilite)
    if actif is not None:
        q = q.filter_by(actif=bool(actif))
    plages = q.all()
    return [
        {
            "id": p.id,
            "type_seance_id": p.type_seance_id,
            "type_seance_nom": p.type_seance.nom if p.type_seance else None,
            "type_seance_couleur": p.type_seance.couleur_hex if p.type_seance else "#B8922A",
            "lieu_id": p.lieu_id,
            "lieu_nom": p.lieu.nom if p.lieu else None,
            "jour_semaine": p.jour_semaine,
            "date_unique": p.date_unique.isoformat() if p.date_unique else None,
            "heure_debut": p.heure_debut,
            "heure_fin": p.heure_fin,
            "valide_du": p.valide_du.date().isoformat() if p.valide_du else None,
            "valide_au": p.valide_au.date().isoformat() if p.valide_au else None,
            "actif": p.actif,
        }
        for p in plages
    ]


@api_router.get("/indisponibilites")
def api_lister_indisponibilites(session: Session = Depends(obtenir_session)):
    """Liste les indisponibilités (utilisé par le JS d'agenda admin)."""
    indispos = (
        session.query(IndisponibiliteAgenda)
        .order_by(IndisponibiliteAgenda.date_debut)
        .all()
    )
    return [
        {
            "id": i.id,
            "date_debut": i.date_debut.isoformat(),
            "date_fin": i.date_fin.isoformat(),
            "motif": i.motif,
        }
        for i in indispos
    ]


@api_router.get("/creneaux-semaine")
def api_creneaux_semaine(
    debut: Optional[str] = None,
    fin: Optional[str] = None,
    session: Session = Depends(obtenir_session),
):
    """Retourne tous les créneaux générés par les plages de disponibilité pour une semaine.
    Format : liste de {date, heure_debut, heure_fin, type_seance, couleur, lieu}."""
    try:
        dt_debut = date.fromisoformat(debut) if debut else date.today()
        dt_fin = date.fromisoformat(fin) if fin else dt_debut + timedelta(days=6)
    except ValueError:
        raise HTTPException(status_code=400, detail="Format de date invalide (YYYY-MM-DD attendu).")

    plages = (
        session.query(PlageDisponibilite)
        .filter_by(actif=True)
        .all()
    )

    bandeaux = []
    d = dt_debut
    while d <= dt_fin:
        for plage in plages:
            # Vérifier validité de période
            if plage.valide_du and d < plage.valide_du.date():
                continue
            if plage.valide_au and d > plage.valide_au.date():
                continue

            # Vérifier si la plage couvre ce jour
            couvre = False
            if plage.date_unique:
                couvre = plage.date_unique.date() == d
            elif plage.jour_semaine is not None:
                couvre = d.weekday() == plage.jour_semaine

            if not couvre:
                continue

            # Un seul bandeau par plage, de heure_debut à heure_fin
            # (ignore les pauses — juste l'enveloppe de la plage)
            bandeaux.append({
                "date": d.isoformat(),
                "plage_id": plage.id,
                "heure_debut": plage.heure_debut,
                "heure_fin": plage.heure_fin,
                "type_seance_id": plage.type_seance_id,
                "type_seance_nom": plage.type_seance.nom if plage.type_seance else "",
                "duree_minutes": plage.type_seance.duree_minutes if plage.type_seance else 60,
                "modalite": plage.type_seance.modalite if plage.type_seance else "",
                "couleur": plage.type_seance.couleur_hex if plage.type_seance else "#B8922A",
                "lieu_nom": plage.lieu.nom if plage.lieu else "",
                "lieu_id": plage.lieu_id,
            })
        d += timedelta(days=1)

    return bandeaux


@api_router.get("/semaine")
def api_semaine(
    debut: Optional[str] = None,
    fin: Optional[str] = None,
    session: Session = Depends(obtenir_session),
):
    """Retourne les réservations pour une plage de dates (vue semaine admin)."""
    maintenant = datetime.utcnow()
    try:
        dt_debut = datetime.fromisoformat(debut) if debut else maintenant.replace(hour=0, minute=0, second=0)
        dt_fin = datetime.fromisoformat(fin) if fin else dt_debut + timedelta(days=7)
    except ValueError:
        raise HTTPException(status_code=400, detail="Format de date invalide.")

    reservations = (
        session.query(Reservation)
        .filter(
            Reservation.date_debut >= dt_debut,
            Reservation.date_debut <= dt_fin,
            Reservation.statut != "annulee",
        )
        .order_by(Reservation.date_debut)
        .all()
    )
    return [_serialiser_reservation(r) for r in reservations]


@api_router.get("/reservations")
def api_lister_reservations(
    statut: Optional[str] = None,
    date_filtre: Optional[str] = None,
    session: Session = Depends(obtenir_session),
):
    """Liste les réservations avec filtres optionnels (admin JS)."""
    q = session.query(Reservation)
    if statut:
        q = q.filter_by(statut=statut)
    if date_filtre:
        try:
            d = date.fromisoformat(date_filtre)
            debut_jour = datetime.combine(d, time(0, 0))
            fin_jour = datetime.combine(d, time(23, 59))
            q = q.filter(Reservation.date_debut >= debut_jour, Reservation.date_debut <= fin_jour)
        except ValueError:
            pass
    reservations = q.order_by(Reservation.date_debut.desc()).limit(200).all()
    return [_serialiser_reservation(r) for r in reservations]


@api_router.get("/reservations/{reservation_id}")
def api_detail_reservation(
    reservation_id: int,
    session: Session = Depends(obtenir_session),
):
    """Détail d'une réservation (admin JS)."""
    resa = session.get(Reservation, reservation_id)
    if not resa:
        raise HTTPException(status_code=404, detail="Réservation introuvable.")
    return _serialiser_reservation(resa)


# ===========================================================================
# API PUBLIQUE — Disponibilités et réservation
# ===========================================================================

def _plage_valide_pour_date(plage: PlageDisponibilite, pour_date: date) -> bool:
    """Vérifie que la plage est valide pour une date donnée (période valide_du / valide_au)."""
    if plage.valide_du and pour_date < plage.valide_du.date():
        return False
    if plage.valide_au and pour_date > plage.valide_au.date():
        return False
    return True


def _creneaux_pour_plage(plage: PlageDisponibilite, pour_date: date) -> list[tuple]:
    """Calcule les créneaux disponibles pour une plage sur une date donnée.
    Retourne une liste de (heure_debut_str, heure_fin_str).
    Le temps de repos (pause_apres_minutes) est pris en compte pour l'espacement
    entre créneaux : le créneau suivant ne peut démarrer qu'après duree + repos.
    Tient compte de la période de validité (valide_du / valide_au)."""
    # Vérifier la période de validité
    if not _plage_valide_pour_date(plage, pour_date):
        return []

    ts = plage.type_seance
    duree = ts.duree_minutes
    repos = ts.pause_apres_minutes or 0  # temps de repos après séance
    h_debut = [int(x) for x in plage.heure_debut.split(":")]
    h_fin = [int(x) for x in plage.heure_fin.split(":")]
    pause_d = [int(x) for x in plage.pause_debut.split(":")] if plage.pause_debut else None
    pause_f = [int(x) for x in plage.pause_fin.split(":")] if plage.pause_fin else None

    debut = time(h_debut[0], h_debut[1])
    fin_plage = time(h_fin[0], h_fin[1])

    creneaux = []
    curseur = debut
    while True:
        fin_creneau_dt = (datetime.combine(date.today(), curseur) + timedelta(minutes=duree)).time()
        if fin_creneau_dt > fin_plage:
            break

        # Exclure si dans la pause méridienne
        dans_pause = False
        if pause_d and pause_f:
            p_d = time(pause_d[0], pause_d[1])
            p_f = time(pause_f[0], pause_f[1])
            if curseur < p_f and fin_creneau_dt > p_d:
                dans_pause = True

        if not dans_pause:
            creneaux.append((
                curseur.strftime("%H:%M"),
                fin_creneau_dt.strftime("%H:%M"),
            ))

        # Avancer de duree + repos pour positionner le prochain créneau
        curseur = (datetime.combine(date.today(), curseur) + timedelta(minutes=duree + repos)).time()

    return creneaux


def _indispo_pour_datetime(dt: datetime, session: Session) -> bool:
    """Retourne True si le datetime donné est couvert par une indisponibilité."""
    return session.query(IndisponibiliteAgenda).filter(
        IndisponibiliteAgenda.date_debut <= dt,
        IndisponibiliteAgenda.date_fin >= dt,
    ).first() is not None


def _indispos_du_jour(d: date, session: Session) -> list:
    """Retourne les indisponibilités qui chevauchent une journée donnée."""
    debut_jour = datetime.combine(d, time(0, 0))
    fin_jour = datetime.combine(d, time(23, 59))
    return session.query(IndisponibiliteAgenda).filter(
        IndisponibiliteAgenda.date_debut <= fin_jour,
        IndisponibiliteAgenda.date_fin >= debut_jour,
    ).all()


@api_router.get("/disponibilites")
def disponibilites(
    type_seance_id: int,
    mois: Optional[str] = None,       # "YYYY-MM" (legacy)
    annee: Optional[int] = None,       # depuis le template public
    mois_num_param: Optional[int] = None,  # param nommé "mois" en int — alias géré ci-dessous
    modalite: Optional[str] = None,    # ignoré pour le filtrage, juste accepté
    session: Session = Depends(obtenir_session),
):
    """Retourne les jours disponibles pour un type de séance dans un mois donné.
    Accepte soit mois='YYYY-MM' (legacy) soit annee=YYYY&mois=MM (template public)."""
    # Le template envoie annee=YYYY&mois=MM (entiers) ; on unifie ici
    import re
    if mois and re.match(r"^\d{4}-\d{2}$", str(mois)):
        try:
            annee, mois_num = int(mois.split("-")[0]), int(mois.split("-")[1])
        except (ValueError, IndexError):
            raise HTTPException(status_code=400, detail="Format de mois invalide (YYYY-MM attendu).")
    elif annee and mois:
        # mois est passé comme entier (ex: ?annee=2026&mois=3)
        try:
            mois_num = int(mois)
        except ValueError:
            raise HTTPException(status_code=400, detail="Paramètre mois invalide.")
    else:
        raise HTTPException(status_code=400, detail="Paramètres mois invalides. Utiliser mois=YYYY-MM ou annee=YYYY&mois=MM.")

    ts = session.get(TypeSeance, type_seance_id)
    if not ts or not ts.actif:
        raise HTTPException(status_code=404, detail="Type de séance introuvable.")

    plages = (
        session.query(PlageDisponibilite)
        .filter_by(type_seance_id=type_seance_id, actif=True)
        .all()
    )

    # Construire le calendrier du mois
    import calendar
    _, nb_jours = calendar.monthrange(annee, mois_num)
    jours_disponibles = []

    for jour in range(1, nb_jours + 1):
        d = date(annee, mois_num, jour)
        if d < date.today():
            continue

        # Si tout le jour est en indisponibilité, pas besoin de vérifier les plages
        indispos_jour = _indispos_du_jour(d, session)

        # Trouver les plages qui couvrent ce jour
        for plage in plages:
            couvre = False
            if plage.date_unique:
                couvre = plage.date_unique.date() == d
            elif plage.jour_semaine is not None:
                couvre = d.weekday() == plage.jour_semaine

            if not couvre:
                continue

            creneaux = _creneaux_pour_plage(plage, d)
            if not creneaux:
                continue

            # Filtrer les créneaux déjà réservés
            debut_jour = datetime.combine(d, time(0, 0))
            fin_jour = datetime.combine(d, time(23, 59))
            reservations_jour = (
                session.query(Reservation)
                .filter(
                    Reservation.date_debut >= debut_jour,
                    Reservation.date_debut <= fin_jour,
                    Reservation.type_seance_id == type_seance_id,
                    Reservation.statut == "en_attente",
                )
                .all()
            )
            heures_prises = {r.date_debut.strftime("%H:%M") for r in reservations_jour}

            # Filtrer les créneaux bloqués par une indisponibilité
            def _heure_en_indispo(h: str) -> bool:
                dt_test = datetime.combine(d, time(int(h[:2]), int(h[3:])))
                return any(i.date_debut <= dt_test <= i.date_fin for i in indispos_jour)

            creneaux_libres = [
                c for c in creneaux
                if c[0] not in heures_prises and not _heure_en_indispo(c[0])
            ]

            if creneaux_libres:
                jours_disponibles.append(d.isoformat())
                break  # Ce jour a au moins un créneau libre

    return {"jours_disponibles": jours_disponibles}


@api_router.get("/creneaux")
def creneaux_du_jour(
    type_seance_id: int,
    date_str: str,  # "YYYY-MM-DD"
    session: Session = Depends(obtenir_session),
):
    """Retourne les créneaux disponibles pour un type de séance à une date donnée."""
    try:
        d = date.fromisoformat(date_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Format de date invalide (YYYY-MM-DD attendu).")

    if d < date.today():
        return {"creneaux": []}

    ts = session.get(TypeSeance, type_seance_id)
    if not ts or not ts.actif:
        raise HTTPException(status_code=404, detail="Type de séance introuvable.")

    plages = (
        session.query(PlageDisponibilite)
        .filter_by(type_seance_id=type_seance_id, actif=True)
        .all()
    )

    tous_creneaux = []
    for plage in plages:
        couvre = False
        if plage.date_unique:
            couvre = plage.date_unique.date() == d
        elif plage.jour_semaine is not None:
            couvre = d.weekday() == plage.jour_semaine

        if couvre:
            tous_creneaux.extend(_creneaux_pour_plage(plage, d))

    # Dédoublonner et trier
    tous_creneaux = sorted(set(tous_creneaux), key=lambda c: c[0])

    # Filtrer les créneaux réservés
    debut_jour = datetime.combine(d, time(0, 0))
    fin_jour = datetime.combine(d, time(23, 59))
    reservations_jour = (
        session.query(Reservation)
        .filter(
            Reservation.date_debut >= debut_jour,
            Reservation.date_debut <= fin_jour,
            Reservation.type_seance_id == type_seance_id,
            Reservation.statut == "en_attente",
        )
        .all()
    )
    heures_prises = {r.date_debut.strftime("%H:%M") for r in reservations_jour}

    # Filtrer les créneaux bloqués par une indisponibilité
    indispos_jour = _indispos_du_jour(d, session)
    def _heure_en_indispo_creneaux(h: str) -> bool:
        dt_test = datetime.combine(d, time(int(h[:2]), int(h[3:])))
        return any(i.date_debut <= dt_test <= i.date_fin for i in indispos_jour)

    creneaux_libres = [
        {"debut": c[0], "fin": c[1]}
        for c in tous_creneaux
        if c[0] not in heures_prises and not _heure_en_indispo_creneaux(c[0])
    ]

    # Trouver le lieu associé à ces plages
    lieux_ids = list({p.lieu_id for p in plages if (
        (p.date_unique and p.date_unique.date() == d) or
        (p.jour_semaine is not None and d.weekday() == p.jour_semaine)
    )})
    lieux = []
    for l_id in lieux_ids:
        lieu = session.get(Lieu, l_id)
        if lieu:
            lieux.append({"id": lieu.id, "nom": lieu.nom, "type_lieu": lieu.type_lieu})

    return {"creneaux": creneaux_libres, "lieux": lieux}


@api_router.post("/connexion-rdv")
async def connexion_rdv(request: Request, session: Session = Depends(obtenir_session)):
    """Connexion légère depuis la page de réservation.
    Body JSON : { email, mot_de_passe }
    Retourne les infos pré-remplissage si succès (pas de session cookie, juste les données).
    """
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Corps JSON invalide.")

    email_norm = (data.get("email") or "").strip().lower()
    mdp = data.get("mot_de_passe") or ""
    if not email_norm or not mdp:
        raise HTTPException(status_code=400, detail="Email et mot de passe requis.")

    eleve = session.query(Eleve).filter_by(email=email_norm).first()
    if not eleve or not eleve.mot_de_passe_hash:
        raise HTTPException(status_code=401, detail="Identifiants incorrects.")
    if not eleve.verifier_mot_de_passe(mdp):
        raise HTTPException(status_code=401, detail="Identifiants incorrects.")

    return {
        "ok": True,
        "prenom": eleve.prenom or "",
        "nom": eleve.nom or "",
        "email": eleve.email,
        "telephone": eleve.telephone or "",
        "eleve_id": eleve.id,
    }


@api_router.post("/reserver")
async def reserver(request: Request, session: Session = Depends(obtenir_session)):
    """Crée une réservation depuis le formulaire public et envoie l'email de confirmation.
    Accepte deux formats :
      - Ancien : {type_seance_id, lieu_id, date_debut (ISO), prenom, nom, email}
      - Nouveau (template public) : {type_seance_id, modalite, date, heure_debut, prenom, nom, email}
    """
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Corps JSON invalide.")

    # Validation minimale
    champs_requis = ["type_seance_id", "prenom", "nom", "email"]
    for champ in champs_requis:
        if not data.get(champ):
            raise HTTPException(status_code=400, detail=f"Champ requis manquant : {champ}")

    # Construire dt_debut depuis date+heure_debut OU date_debut ISO
    if data.get("date") and data.get("heure_debut"):
        try:
            dt_debut = datetime.fromisoformat(f"{data['date']}T{data['heure_debut']}:00")
        except ValueError:
            raise HTTPException(status_code=400, detail="Format date/heure_debut invalide.")
    elif data.get("date_debut"):
        try:
            dt_debut = datetime.fromisoformat(data["date_debut"])
        except ValueError:
            raise HTTPException(status_code=400, detail="Format de date invalide.")
    else:
        raise HTTPException(status_code=400, detail="Champ requis manquant : date+heure_debut ou date_debut")

    ts = session.get(TypeSeance, int(data["type_seance_id"]))
    if not ts or not ts.actif:
        raise HTTPException(status_code=404, detail="Type de séance introuvable.")

    # Déterminer le lieu
    modalite_demandee = data.get("modalite")  # "cabinet" | "visio" | None
    if data.get("lieu_id"):
        lieu = session.get(Lieu, int(data["lieu_id"]))
        if not lieu or not lieu.actif:
            raise HTTPException(status_code=404, detail="Lieu introuvable.")
    else:
        # Auto-détection depuis les plages du créneau et la modalité demandée
        plages_actives = (
            session.query(PlageDisponibilite)
            .filter_by(type_seance_id=ts.id, actif=True)
            .all()
        )
        d_resa = dt_debut.date()
        plages_du_jour = [
            p for p in plages_actives
            if (p.date_unique and p.date_unique.date() == d_resa) or
               (p.jour_semaine is not None and d_resa.weekday() == p.jour_semaine)
        ]
        lieu = None
        for plage in plages_du_jour:
            l = session.get(Lieu, plage.lieu_id) if plage.lieu_id else None
            if not l or not l.actif:
                continue
            if modalite_demandee == "visio" and l.type_lieu != "visio":
                continue
            if modalite_demandee == "cabinet" and l.type_lieu not in ("cabinet", "domicile"):
                continue
            lieu = l
            break
        if not lieu:
            # Fallback : premier lieu actif
            lieu = session.query(Lieu).filter_by(actif=True).first()
        if not lieu:
            raise HTTPException(status_code=400, detail="Aucun lieu disponible pour ce créneau.")

    # Vérifier que le créneau est toujours libre
    conflit = (
        session.query(Reservation)
        .filter(
            Reservation.type_seance_id == ts.id,
            Reservation.date_debut == dt_debut,
            Reservation.statut == "en_attente",
        )
        .first()
    )
    if conflit:
        raise HTTPException(status_code=409, detail="Ce créneau vient d'être réservé. Veuillez en choisir un autre.")

    dt_fin = dt_debut + timedelta(minutes=ts.duree_minutes)

    # Lien visio unique : on utilise le lien du lieu (à terme : lien by-session via Whereby/Jitsi)
    lien_visio = None
    if lieu.type_lieu == "visio" and lieu.lien_visio:
        lien_visio = lieu.lien_visio

    # Chercher ou créer un élève
    email_norm = data["email"].strip().lower()
    prenom_str = data["prenom"].strip()
    nom_str = data["nom"].strip()
    tel_str = data.get("telephone", "").strip() or None
    eleve = session.query(Eleve).filter_by(email=email_norm).first()

    compte_cree = False
    lien_mdp = None
    if not eleve and data.get("creer_compte"):
        # Créer un compte élève sans mot de passe ; la cliente le définira via email
        from ..models import generer_token_reinitialisation, TokenAuthentification
        from ..config import URL_PLATEFORME
        eleve = Eleve(
            prenom=prenom_str,
            nom=nom_str,
            email=email_norm,
            telephone=tel_str,
            actif=True,
        )
        session.add(eleve)
        session.flush()
        # Générer un token de définition de mot de passe (valable 7 jours)
        token_str = generer_token_reinitialisation()
        token_obj = TokenAuthentification(
            eleve_id=eleve.id,
            token=token_str,
            type_token="reinitialisation",
            expire_le=datetime.now() + timedelta(days=7),
        )
        session.add(token_obj)
        session.flush()
        lien_mdp = f"{URL_PLATEFORME}/eleve/reinitialiser-mot-de-passe?token={token_str}"
        compte_cree = True

    resa = Reservation(
        type_seance_id=ts.id,
        lieu_id=lieu.id,
        eleve_id=eleve.id if eleve else None,
        prenom=prenom_str,
        nom=nom_str,
        email=email_norm,
        telephone=tel_str,
        message=data.get("message", "").strip() or None,
        date_debut=dt_debut,
        date_fin=dt_fin,
        statut="en_attente",
        source="publique",
        lien_visio_unique=lien_visio,
    )
    session.add(resa)
    session.flush()  # pour avoir resa.id

    session.commit()

    # Envoyer email de définition de mot de passe si compte créé
    if compte_cree and lien_mdp:
        try:
            from ..emails import email_definition_mot_de_passe
            email_definition_mot_de_passe(email_norm, prenom_str, lien_mdp)
        except Exception:
            pass  # best-effort

    # Envoyer l'email de confirmation avec .ics
    try:
        from ..emails_agenda import email_confirmation_reservation
        ok = email_confirmation_reservation(
            destinataire=resa.email,
            prenom=resa.prenom,
            reservation=resa,
            type_seance=ts,
            lieu=lieu,
        )
        if ok:
            session.add(RappelEnvoye(
                reservation_id=resa.id,
                type_rappel="confirmation",
                succes=True,
            ))
            resa.ics_envoye = True
            session.commit()
    except Exception:
        pass  # L'email est best-effort, la réservation est confirmée quoi qu'il arrive

    return {
        "ok": True,
        "reservation_id": resa.id,
        "token_annulation": resa.token_annulation,
        "message": "Votre rendez-vous est confirmé. Un email de confirmation vous a été envoyé.",
    }


@api_router.post("/paiement")
async def creer_paiement_rdv(request: Request, session: Session = Depends(obtenir_session)):
    """Crée une session Stripe Checkout pour une réservation d'agenda.
    Body JSON : { token_annulation: "...", url_retour: "https://..." }
    Retourne : { checkout_url: "https://checkout.stripe.com/..." }
    Si mode_paiement='sans_paiement' ou prix=0, confirme directement sans Stripe.
    """
    try:
        import stripe as _stripe
        _stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
    except ImportError:
        raise HTTPException(status_code=500, detail="Module Stripe non installé.")

    data = await request.json()
    token = data.get("token_annulation", "")
    url_retour = data.get("url_retour", "")

    resa = session.query(Reservation).filter_by(token_annulation=token).first()
    if not resa:
        raise HTTPException(status_code=404, detail="Réservation introuvable.")
    if resa.statut != "en_attente":
        raise HTTPException(status_code=400, detail="Cette réservation n'est plus en attente.")

    ts = resa.type_seance
    prix = float(ts.prix) if ts and ts.prix else 0.0
    mode_paiement = (ts.mode_paiement or "sans_paiement") if ts else "sans_paiement"

    # Paiement non requis ou gratuit → on retourne simplement la page de confirmation
    if mode_paiement == "sans_paiement" or prix <= 0:
        url_base = os.environ.get("URL_PLATEFORME", "https://lms-formation.onrender.com")
        return {"checkout_url": f"{url_base}/rendez-vous/confirmation?token={token}"}

    # Stripe actif
    if not _stripe.api_key:
        raise HTTPException(status_code=503, detail="Paiement indisponible (configuration Stripe manquante).")

    url_base = os.environ.get("URL_PLATEFORME", "https://lms-formation.onrender.com")
    nom_seance = ts.nom if ts else "Séance"

    checkout_session = _stripe.checkout.Session.create(
        mode="payment",
        line_items=[{
            "price_data": {
                "currency": "eur",
                "product_data": {"name": nom_seance},
                "unit_amount": round(prix * 100),
            },
            "quantity": 1,
        }],
        customer_email=resa.email,
        success_url=f"{url_base}/rendez-vous/confirmation?token={token}&stripe_ok=1",
        cancel_url=f"{url_base}/rendez-vous?annule=1",
        metadata={"token_annulation": token, "reservation_id": str(resa.id)},
    )

    resa.stripe_checkout_session_id = checkout_session.id
    session.commit()
    return {"checkout_url": checkout_session.url}


@api_router.post("/annuler/{token}")
def annuler_reservation(token: str, session: Session = Depends(obtenir_session)):
    """Annulation d'une réservation via le token reçu par email."""
    resa = session.query(Reservation).filter_by(token_annulation=token).first()
    if not resa:
        raise HTTPException(status_code=404, detail="Réservation introuvable.")
    if resa.statut == "annulee":
        return {"ok": True, "message": "Cette réservation est déjà annulée."}
    if resa.statut == "realisee":
        raise HTTPException(status_code=400, detail="Impossible d'annuler une séance déjà réalisée.")

    # Vérifier que la séance n'est pas dans moins de 24h
    delai = resa.date_debut - datetime.utcnow()
    if delai.total_seconds() < 86400:
        raise HTTPException(
            status_code=400,
            detail="L'annulation n'est plus possible moins de 24h avant la séance. Contactez Laurence directement.",
        )

    resa.statut = "annulee"
    session.commit()

    return {"ok": True, "message": "Votre rendez-vous a bien été annulé."}


# ===========================================================================
# PAGE PUBLIQUE — /rendez-vous
# ===========================================================================

@public_router.get("/rendez-vous", response_class=HTMLResponse)
def page_rendez_vous(
    request: Request,
    acces: Optional[str] = None,
    session: Session = Depends(obtenir_session),
):
    """Page publique de réservation en ligne.
    ?acces=CODE débloque les types de séance 'lien' ayant ce code.
    Si une élève est connectée, ses infos sont passées pour pré-remplissage.
    """
    all_ts = (
        session.query(TypeSeance)
        .filter_by(actif=True)
        .order_by(TypeSeance.ordre)
        .all()
    )
    code = (acces or "").strip().lower()
    if code:
        types_seances = [t for t in all_ts if (t.visibilite or "public") in ("public", "lien")
                         and ((t.visibilite or "public") == "public" or (t.code_acces or "").lower() == code)]
    else:
        types_seances = [t for t in all_ts if (t.visibilite or "public") == "public"]

    # Pré-sélection : si un seul type correspond au code, on le pré-sélectionne
    type_preselect_id = None
    if code:
        lien_types = [t for t in types_seances if (t.visibilite or "public") == "lien"
                      and (t.code_acces or "").lower() == code]
        if len(lien_types) == 1:
            type_preselect_id = lien_types[0].id

    # Infos élève connectée (pour pré-remplir le formulaire) — sérialisées en JSON côté Python
    import json as _json
    eleve_info_json = "null"
    eleve_id_session = request.session.get("eleve_id")
    if eleve_id_session:
        eleve = session.get(Eleve, eleve_id_session)
        if eleve and eleve.actif:
            eleve_info_json = _json.dumps({
                "id": eleve.id,
                "prenom": eleve.prenom or "",
                "nom": eleve.nom or "",
                "email": eleve.email or "",
                "telephone": eleve.telephone or "",
            })

    return templates.TemplateResponse(
        request,
        "rendez_vous.html",
        {
            "types_seances": types_seances,
            "code_acces": code,
            "type_preselect_id": type_preselect_id if type_preselect_id else "null",
            "eleve_info_json": eleve_info_json,
        },
    )


@public_router.get("/rendez-vous/confirmation", response_class=HTMLResponse)
def page_confirmation_rdv_query(
    token: Optional[str] = None,
    request: Request = None,
    session: Session = Depends(obtenir_session),
):
    """Page de confirmation via query param ?token= (envoi depuis le JS public)."""
    if not token:
        raise HTTPException(status_code=400, detail="Token manquant.")
    resa = session.query(Reservation).filter_by(token_annulation=token).first()
    if not resa:
        raise HTTPException(status_code=404, detail="Réservation introuvable.")
    return templates.TemplateResponse(
        request,
        "rendez_vous_confirmation.html",
        {
            "reservation": resa,
            "type_seance": resa.type_seance,
            "lieu": resa.lieu,
        },
    )


@public_router.get("/rendez-vous/confirmation/{token}", response_class=HTMLResponse)
def page_confirmation_rendez_vous(
    token: str,
    request: Request,
    session: Session = Depends(obtenir_session),
):
    """Page de confirmation après réservation (path param, liens email)."""
    resa = session.query(Reservation).filter_by(token_annulation=token).first()
    if not resa:
        raise HTTPException(status_code=404, detail="Réservation introuvable.")
    return templates.TemplateResponse(
        request,
        "rendez_vous_confirmation.html",
        {
            "reservation": resa,
            "type_seance": resa.type_seance,
            "lieu": resa.lieu,
        },
    )


@public_router.get("/rendez-vous/annuler/{token}", response_class=HTMLResponse)
def page_annuler_rendez_vous(
    token: str,
    request: Request,
    session: Session = Depends(obtenir_session),
):
    """Page d'annulation depuis le lien email."""
    resa = session.query(Reservation).filter_by(token_annulation=token).first()
    if not resa:
        return templates.TemplateResponse(
            request,
            "rendez_vous_annulation.html",
            {"reservation": None, "token": token, "erreur": "introuvable"},
        )
    return templates.TemplateResponse(
        request,
        "rendez_vous_annulation.html",
        {"reservation": resa, "token": token},
    )


@public_router.post("/rendez-vous/annuler/{token}", response_class=HTMLResponse)
def confirmer_annulation_rendez_vous(
    token: str,
    request: Request,
    session: Session = Depends(obtenir_session),
):
    """Traitement du formulaire d'annulation depuis la page publique."""
    resa = session.query(Reservation).filter_by(token_annulation=token).first()
    if not resa:
        return templates.TemplateResponse(
            request,
            "rendez_vous_annulation.html",
            {"reservation": None, "token": token, "erreur": "introuvable"},
        )
    if resa.statut == "annulee":
        return templates.TemplateResponse(
            request,
            "rendez_vous_annulation.html",
            {"reservation": resa, "token": token, "erreur": "deja_annulee"},
        )
    # Vérifier délai 24h
    delai = resa.date_debut - datetime.utcnow()
    if delai.total_seconds() < 86400:
        return templates.TemplateResponse(
            request,
            "rendez_vous_annulation.html",
            {"reservation": resa, "token": token, "erreur": "trop_tard"},
        )
    resa.statut = "annulee"
    session.commit()
    return templates.TemplateResponse(
        request,
        "rendez_vous_annulation.html",
        {"reservation": resa, "token": token, "annulation_ok": True},
    )


# ===========================================================================
# CRON — Rappels automatiques
# ===========================================================================

@cron_router.post("/agenda-rappels")
def cron_rappels(session: Session = Depends(obtenir_session)):
    """Envoi des rappels J-7, J-1 et suivi post-séance.
    À appeler via un cron Render (toutes les heures suffit).
    Idempotent : ne renvoie pas un rappel déjà envoyé."""
    from ..emails_agenda import email_rappel_reservation, email_suivi_post_seance

    maintenant = datetime.utcnow()
    resultats = {"j7": 0, "j1": 0, "post": 0, "erreurs": 0}

    # Rappels J-7 (entre 6j23h et 7j01h)
    j7_min = maintenant + timedelta(days=6, hours=23)
    j7_max = maintenant + timedelta(days=7, hours=1)
    resa_j7 = (
        session.query(Reservation)
        .filter(
            Reservation.date_debut >= j7_min,
            Reservation.date_debut <= j7_max,
            Reservation.statut == "en_attente",
        )
        .all()
    )
    for resa in resa_j7:
        deja = session.query(RappelEnvoye).filter_by(
            reservation_id=resa.id, type_rappel="rappel_j7"
        ).first()
        if deja:
            continue
        ok = email_rappel_reservation(resa, resa.type_seance, resa.lieu, "j7")
        session.add(RappelEnvoye(reservation_id=resa.id, type_rappel="rappel_j7", succes=ok))
        resultats["j7" if ok else "erreurs"] += 1

    # Rappels J-1 (entre 23h et 25h avant)
    j1_min = maintenant + timedelta(hours=23)
    j1_max = maintenant + timedelta(hours=25)
    resa_j1 = (
        session.query(Reservation)
        .filter(
            Reservation.date_debut >= j1_min,
            Reservation.date_debut <= j1_max,
            Reservation.statut == "en_attente",
        )
        .all()
    )
    for resa in resa_j1:
        deja = session.query(RappelEnvoye).filter_by(
            reservation_id=resa.id, type_rappel="rappel_j1"
        ).first()
        if deja:
            continue
        ok = email_rappel_reservation(resa, resa.type_seance, resa.lieu, "j1")
        session.add(RappelEnvoye(reservation_id=resa.id, type_rappel="rappel_j1", succes=ok))
        resultats["j1" if ok else "erreurs"] += 1

    # Suivi post-séance (24h à 26h après la séance)
    post_min = maintenant - timedelta(hours=26)
    post_max = maintenant - timedelta(hours=24)
    resa_post = (
        session.query(Reservation)
        .filter(
            Reservation.date_debut >= post_min,
            Reservation.date_debut <= post_max,
            Reservation.statut.in_(["en_attente", "realisee"]),
        )
        .all()
    )
    for resa in resa_post:
        deja = session.query(RappelEnvoye).filter_by(
            reservation_id=resa.id, type_rappel="suivi_post_seance"
        ).first()
        if deja:
            continue
        ok = email_suivi_post_seance(resa)
        session.add(RappelEnvoye(reservation_id=resa.id, type_rappel="suivi_post_seance", succes=ok))
        resultats["post" if ok else "erreurs"] += 1

    session.commit()
    return resultats


# ===========================================================================
# Utilitaires
# ===========================================================================

def _serialiser_reservation(r: Reservation) -> dict:
    return {
        "id": r.id,
        "prenom": r.prenom,
        "nom": r.nom,
        "email": r.email,
        "telephone": r.telephone,
        "message": r.message,
        "date_debut": r.date_debut.isoformat() if r.date_debut else None,
        "date_fin": r.date_fin.isoformat() if r.date_fin else None,
        "statut": r.statut,
        "source": r.source,
        "type_seance": r.type_seance.nom if r.type_seance else None,
        "type_seance_couleur": r.type_seance.couleur_hex if r.type_seance else "#B8922A",
        "modalite": r.type_seance.modalite if r.type_seance else "cabinet",
        "lieu_nom": r.lieu.nom if r.lieu else None,
        "lien_visio_unique": r.lien_visio_unique,
        "ics_envoye": r.ics_envoye,
        "note_admin": r.note_admin,
        "token_annulation": r.token_annulation,
        "eleve_id": r.eleve_id,
    }


# ===========================================================================
# WEBHOOK Stripe — Paiement agenda
# ===========================================================================

@webhook_router.post("/webhooks/agenda-stripe")
async def webhook_stripe_agenda(request: Request, session: Session = Depends(obtenir_session)):
    """Webhook Stripe : confirme le paiement d'un RDV agenda.
    Stripe appelle cette URL automatiquement après un paiement réussi.
    """
    import json as _json
    try:
        import stripe as _stripe
    except ImportError:
        raise HTTPException(status_code=500, detail="Module Stripe non installé.")

    _stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET_AGENDA", "")

    payload = await request.body()
    signature = request.headers.get("stripe-signature", "")

    try:
        if webhook_secret:
            event_obj = _stripe.Webhook.construct_event(payload, signature, webhook_secret)
            event = _json.loads(payload)
        else:
            event = _json.loads(payload)
    except Exception:
        raise HTTPException(status_code=400, detail="Signature webhook invalide.")

    type_event = event.get("type", "")
    if type_event != "checkout.session.completed":
        return {"ok": True, "ignored": True}

    stripe_session = event.get("data", {}).get("object", {})
    metadata = stripe_session.get("metadata", {})
    token = metadata.get("token_annulation", "")
    montant_recu = stripe_session.get("amount_total", 0)  # en centimes

    if not token:
        return {"ok": True, "ignored": True}

    resa = session.query(Reservation).filter_by(token_annulation=token).first()
    if not resa:
        return {"ok": True, "ignored": True}

    from decimal import Decimal
    resa.prix_paye = Decimal(montant_recu) / 100
    session.commit()
    return {"ok": True}
