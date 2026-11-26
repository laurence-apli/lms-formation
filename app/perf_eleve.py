"""Calculs groupés pour l'espace élève (performance, nov. 2026).

Chaque requête vers Neon coûte ~150 ms depuis Render. Le tableau de bord et le
sommaire d'une formation faisaient une requête par formation / par chapitre
(plus de 150 allers-retours). Ici tout est chargé en quelques requêtes, puis
calculé en Python — avec exactement les mêmes règles que models.py :
  - progression_pourcentage  -> progression()
  - chapitre_est_accessible  -> etats_chapitres()
"""
from sqlalchemy.orm import Session, selectinload, undefer

from .models import (
    Formation, Module, ValidationChapitre,
    chapitre_dans_le_niveau, sequence_chapitres,
)


def charger_formations(session: Session, ids, avec_image: bool = False) -> dict:
    """{id: Formation} avec modules et chapitres préchargés (3 requêtes au total)."""
    ids = list(set(ids))
    if not ids:
        return {}
    options = [selectinload(Formation.modules).selectinload(Module.chapitres)]
    if avec_image:
        options.append(undefer(Formation.image_url))
    formations = session.query(Formation).options(*options).filter(Formation.id.in_(ids)).all()
    return {f.id: f for f in formations}


def ids_chapitres_valides(session: Session, eleve_id: int) -> set:
    """Tous les chapitres validés par l'élève (1 requête)."""
    return {
        cid for (cid,) in session.query(ValidationChapitre.chapitre_id)
        .filter(ValidationChapitre.eleve_id == eleve_id).all()
    }


def progression(formation: Formation, niveau: int, valides: set) -> float:
    """Même calcul que models.progression_pourcentage, sans requête."""
    visibles = [c for c in sequence_chapitres(formation) if chapitre_dans_le_niveau(formation, niveau, c)]
    if not visibles:
        return 0.0
    nb = sum(1 for c in visibles if c.id in valides)
    return round(100 * nb / len(visibles), 1)


def etats_chapitres(formation: Formation, niveau: int, valides: set) -> dict:
    """{chapitre_id: accessible} pour les chapitres du niveau de l'élève.
    Même règle que models.chapitre_est_accessible : un chapitre est accessible si le
    chapitre précédent (dans le niveau de l'élève) est validé, ou s'il est le premier."""
    etats = {}
    precedent = None
    for c in sequence_chapitres(formation):
        if not chapitre_dans_le_niveau(formation, niveau, c):
            continue
        etats[c.id] = precedent is None or precedent.id in valides
        precedent = c
    return etats


# ---------------------------------------------------------------------------
# Photos des formations (cartes du tableau de bord)
# ---------------------------------------------------------------------------
# Les photos sont stockées en base64 dans formations.image_url (jusqu'à 3,5 Mo chacune).
# Les intégrer directement dans la page faisait un tableau de bord de ~40 Mo.
# On sert désormais une version réduite (WebP ~900 px) via /images/formation/{id},
# mise en cache en mémoire et dans le navigateur (l'URL change si la photo change).

def urls_images_formations(session: Session, ids) -> dict:
    """{formation_id: url ou None} SANS lire les images (1 petite requête)."""
    from sqlalchemy import case, func
    ids = list(set(ids))
    if not ids:
        return {}
    lignes = (session.query(
        Formation.id,
        func.length(Formation.image_url),
        case((Formation.image_url.like("data:%"), None), else_=Formation.image_url),
    ).filter(Formation.id.in_(ids)).all())
    res = {}
    for fid, longueur, url_directe in lignes:
        if not longueur:
            res[fid] = None
        elif url_directe:
            res[fid] = url_directe            # image déjà hébergée ailleurs (URL http)
        else:
            res[fid] = f"/images/formation/{fid}?v={longueur}"
    return res


_cache_images: dict = {}


def image_formation_reduite(session: Session, formation_id: int, version: str):
    """(octets, type MIME) de la photo réduite, ou None. Mise en cache par (id, version)."""
    import base64
    import io
    cle = (formation_id, version)
    if cle in _cache_images:
        return _cache_images[cle]
    ligne = session.query(Formation.image_url).filter(Formation.id == formation_id).first()
    if not ligne or not ligne[0] or not ligne[0].startswith("data:"):
        return None
    entete, _, donnees = ligne[0].partition(",")
    try:
        brut = base64.b64decode(donnees)
    except Exception:
        return None
    mime = entete[5:].split(";")[0] or "image/jpeg"
    resultat = (brut, mime)
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(brut))
        img.thumbnail((900, 900))
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA" if "A" in img.getbands() or img.mode == "P" else "RGB")
        sortie = io.BytesIO()
        img.save(sortie, format="WEBP", quality=82, method=4)
        if sortie.tell() < len(brut):
            resultat = (sortie.getvalue(), "image/webp")
    except Exception:
        pass  # Pillow absent ou image illisible : on sert l'original
    if len(_cache_images) > 200:
        _cache_images.clear()
    _cache_images[cle] = resultat
    return resultat
