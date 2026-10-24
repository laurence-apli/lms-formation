"""
Routes de l'agenda natif — remplace Resalib (70€/mois).
Couvre :
  - Admin : paramétrage (types de séances, lieux, plages dispo) + vue agenda
  - Public : page /rendez-vous (réservation 4 étapes)
  - API : disponibilités, création/annulation de réservation
  - Cron : envoi des rappels J-7, J-1 et suivi post-séance
"""
import json
import secrets
from datetime import datetime, timedelta, date, time
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from ..database import obtenir_session
from ..models import (
    TypeSeance, Lieu, PlageDisponibilite, Reservation, RappelEnvoye,
    SeanceAccompagnement, AccesFormation, Eleve, Administrateur,
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
            "modalite": t.modalite, "couleur_hex": t.couleur_hex,
            "description": t.description, "actif": t.actif, "ordre": t.ordre,
        }
        for t in ts
    ]


@admin_router.post("/types-seances")
def creer_type_seance(
    nom: str = Form(...),
    duree_minutes: int = Form(60),
    modalite: str = Form("cabinet"),
    couleur_hex: str = Form("#B8922A"),
    description: str = Form(""),
    session: Session = Depends(obtenir_session),
):
    if not nom.strip():
        raise HTTPException(status_code=400, detail="Le nom est requis.")
    if modalite not in ("cabinet", "visio", "les_deux"):
        raise HTTPException(status_code=400, detail="Modalité invalide.")

    max_ordre = session.query(TypeSeance).count()
    ts = TypeSeance(
        nom=nom.strip(),
        duree_minutes=duree_minutes,
        modalite=modalite,
        couleur_hex=couleur_hex,
        description=description.strip() or None,
        ordre=max_ordre,
    )
    session.add(ts)
    session.commit()
    return {"id": ts.id, "nom": ts.nom}


@admin_router.put("/types-seances/{ts_id}")
def modifier_type_seance(
    ts_id: int,
    nom: str = Form(...),
    duree_minutes: int = Form(60),
    modalite: str = Form("cabinet"),
    couleur_hex: str = Form("#B8922A"),
    description: str = Form(""),
    actif: bool = Form(True),
    session: Session = Depends(obtenir_session),
):
    ts = session.get(TypeSeance, ts_id)
    if not ts:
        raise HTTPException(status_code=404, detail="Type de séance introuvable.")
    ts.nom = nom.strip()
    ts.duree_minutes = duree_minutes
    ts.modalite = modalite
    ts.couleur_hex = couleur_hex
    ts.description = description.strip() or None
    ts.actif = actif
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


@admin_router.post("/lieux")
def creer_lieu(
    nom: str = Form(...),
    adresse: str = Form(""),
    type_lieu: str = Form("cabinet"),
    lien_visio: str = Form(""),
    session: Session = Depends(obtenir_session),
):
    if not nom.strip():
        raise HTTPException(status_code=400, detail="Le nom est requis.")
    if type_lieu not in ("cabinet", "visio", "autre"):
        raise HTTPException(status_code=400, detail="Type de lieu invalide.")

    lieu = Lieu(
        nom=nom.strip(),
        adresse=adresse.strip() or None,
        type_lieu=type_lieu,
        lien_visio=lien_visio.strip() or None,
    )
    session.add(lieu)
    session.commit()
    return {"id": lieu.id, "nom": lieu.nom}


@admin_router.put("/lieux/{lieu_id}")
def modifier_lieu(
    lieu_id: int,
    nom: str = Form(...),
    adresse: str = Form(""),
    type_lieu: str = Form("cabinet"),
    lien_visio: str = Form(""),
    actif: bool = Form(True),
    session: Session = Depends(obtenir_session),
):
    lieu = session.get(Lieu, lieu_id)
    if not lieu:
        raise HTTPException(status_code=404, detail="Lieu introuvable.")
    lieu.nom = nom.strip()
    lieu.adresse = adresse.strip() or None
    lieu.type_lieu = type_lieu
    lieu.lien_visio = lien_visio.strip() or None
    lieu.actif = actif
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
            "lieu_id": p.lieu_id,
            "lieu_nom": p.lieu.nom if p.lieu else "",
            "jour_semaine": p.jour_semaine,
            "jour_label": jours[p.jour_semaine] if p.jour_semaine is not None else "Date unique",
            "date_unique": p.date_unique.isoformat() if p.date_unique else None,
            "heure_debut": p.heure_debut,
            "heure_fin": p.heure_fin,
            "pause_debut": p.pause_debut,
            "pause_fin": p.pause_fin,
        }
        for p in plages
    ]


@admin_router.post("/plages")
def creer_plage(
    type_seance_id: int = Form(...),
    lieu_id: int = Form(...),
    heure_debut: str = Form(...),
    heure_fin: str = Form(...),
    jour_semaine: Optional[int] = Form(None),
    date_unique: Optional[str] = Form(None),
    pause_debut: str = Form(""),
    pause_fin: str = Form(""),
    session: Session = Depends(obtenir_session),
):
    if jour_semaine is None and not date_unique:
        raise HTTPException(status_code=400, detail="Jour de la semaine ou date unique requis.")

    date_u = None
    if date_unique:
        try:
            date_u = datetime.fromisoformat(date_unique)
        except ValueError:
            raise HTTPException(status_code=400, detail="Format de date invalide.")

    plage = PlageDisponibilite(
        type_seance_id=type_seance_id,
        lieu_id=lieu_id,
        jour_semaine=jour_semaine,
        date_unique=date_u,
        heure_debut=heure_debut,
        heure_fin=heure_fin,
        pause_debut=pause_debut.strip() or None,
        pause_fin=pause_fin.strip() or None,
    )
    session.add(plage)
    session.commit()
    return {"id": plage.id}


@admin_router.delete("/plages/{plage_id}")
def supprimer_plage(plage_id: int, session: Session = Depends(obtenir_session)):
    plage = session.get(PlageDisponibilite, plage_id)
    if not plage:
        raise HTTPException(status_code=404, detail="Plage introuvable.")
    plage.actif = False
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


@admin_router.post("/reservations/{resa_id}/statut")
def changer_statut_reservation(
    resa_id: int,
    statut: str = Form(...),
    note_admin: str = Form(""),
    session: Session = Depends(obtenir_session),
):
    resa = session.get(Reservation, resa_id)
    if not resa:
        raise HTTPException(status_code=404, detail="Réservation introuvable.")
    if statut not in ("en_attente", "annulee", "realisee"):
        raise HTTPException(status_code=400, detail="Statut invalide.")

    resa.statut = statut
    if note_admin:
        resa.note_admin = note_admin.strip()

    # Si marquée réalisée, créer une SeanceAccompagnement si l'élève est connu
    if statut == "realisee" and resa.eleve_id:
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


@admin_router.post("/reservations/{resa_id}/note")
def sauvegarder_note_reservation(
    resa_id: int,
    note_admin: str = Form(""),
    session: Session = Depends(obtenir_session),
):
    """Sauvegarde la note interne d'une réservation (admin)."""
    resa = session.get(Reservation, resa_id)
    if not resa:
        raise HTTPException(status_code=404, detail="Réservation introuvable.")
    resa.note_admin = note_admin.strip() or None
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
    session: Session = Depends(obtenir_session),
):
    """Liste les types de séances (publique + admin JS)."""
    q = session.query(TypeSeance)
    if actif is not None:
        q = q.filter_by(actif=bool(actif))
    ts = q.order_by(TypeSeance.ordre).all()
    return [
        {
            "id": t.id, "nom": t.nom, "duree_minutes": t.duree_minutes,
            "modalite": t.modalite, "couleur_hex": t.couleur_hex,
            "description": t.description, "actif": t.actif, "ordre": t.ordre,
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
            "lieu_id": p.lieu_id,
            "lieu_nom": p.lieu.nom if p.lieu else None,
            "jour_semaine": p.jour_semaine,
            "date_unique": p.date_unique.isoformat() if p.date_unique else None,
            "heure_debut": p.heure_debut,
            "heure_fin": p.heure_fin,
            "actif": p.actif,
        }
        for p in plages
    ]


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

def _creneaux_pour_plage(plage: PlageDisponibilite, pour_date: date) -> list[tuple]:
    """Calcule les créneaux disponibles pour une plage sur une date donnée.
    Retourne une liste de (heure_debut_str, heure_fin_str)."""
    duree = plage.type_seance.duree_minutes
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

        # Exclure si dans la pause
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

        curseur = fin_creneau_dt

    return creneaux


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
            creneaux_libres = [c for c in creneaux if c[0] not in heures_prises]

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

    creneaux_libres = [
        {"debut": c[0], "fin": c[1]}
        for c in tous_creneaux
        if c[0] not in heures_prises
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

    # Chercher un élève existant
    email_norm = data["email"].strip().lower()
    eleve = session.query(Eleve).filter_by(email=email_norm).first()

    resa = Reservation(
        type_seance_id=ts.id,
        lieu_id=lieu.id,
        eleve_id=eleve.id if eleve else None,
        prenom=data["prenom"].strip(),
        nom=data["nom"].strip(),
        email=email_norm,
        telephone=data.get("telephone", "").strip() or None,
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
def page_rendez_vous(request: Request, session: Session = Depends(obtenir_session)):
    """Page publique de réservation en ligne."""
    types_seances = (
        session.query(TypeSeance)
        .filter_by(actif=True)
        .order_by(TypeSeance.ordre)
        .all()
    )
    return templates.TemplateResponse(
        request,
        "rendez_vous.html",
        {
            "types_seances": types_seances,
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
