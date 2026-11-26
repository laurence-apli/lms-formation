"""Images intégrées au contenu (chapitres, présentations) -> Cloudflare R2.

Pourquoi (26/11/2026) : les imports Word/HTML mettent les images DANS le texte, en base64
(20 Mo de texte pour 13 formations). Tout ce poids était relu dans Neon à chaque ouverture
d'une formation en admin, et la base grossit à chaque nouvelle formation.

Ce module :
- extrait chaque <img src="data:image/..."> du HTML, la réduit (1600 px max, WebP),
  la dépose sur R2 sous un nom = empreinte SHA-1 (une même image n'est stockée qu'une fois),
- remplace le src par un lien court /images/contenu/<empreinte>.<ext>,
- ce lien (route dans pages.py) vérifie qu'on est connecté (élève ou admin) puis redirige
  vers une URL R2 signée temporaire. Aucune lecture dans Neon pour afficher une image.

Si R2 n'est pas configuré, le HTML est laissé tel quel (comportement d'avant).
"""
import base64
import hashlib
import io
import logging
import re

from . import stockage_r2

log = logging.getLogger("images_contenu")

DOSSIER = "contenu"
PREFIXE_URL = "/images/contenu/"
COTE_MAX = 1600

# src="data:image/png;base64,...."  (guillemets simples ou doubles)
_MOTIF = re.compile(r"""(src\s*=\s*)(["'])data:(image/[a-zA-Z0-9.+-]+);base64,([A-Za-z0-9+/=\s]+)\2""")

_EXT = {"image/webp": "webp", "image/png": "png", "image/jpeg": "jpg", "image/jpg": "jpg",
        "image/gif": "gif", "image/svg+xml": "svg"}


def _optimiser(brut: bytes, mime: str):
    """(octets, mime) : réduit/convertit en WebP sauf GIF animés et SVG."""
    if mime in ("image/svg+xml", "image/gif"):
        return brut, mime
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(brut))
        img.thumbnail((COTE_MAX, COTE_MAX))
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA" if ("A" in img.getbands() or img.mode == "P") else "RGB")
        sortie = io.BytesIO()
        img.save(sortie, format="WEBP", quality=85, method=4)
        if sortie.tell() < len(brut):
            return sortie.getvalue(), "image/webp"
    except Exception as e:  # noqa: BLE001
        log.warning("Image non optimisée (%s) : %s", mime, e)
    return brut, mime


def _deposer(brut: bytes, mime: str) -> str:
    """Dépose l'image sur R2 (si absente) et renvoie le lien court à mettre dans le HTML."""
    octets, mime_final = _optimiser(brut, mime)
    ext = _EXT.get(mime_final, "bin")
    nom = f"{hashlib.sha1(octets).hexdigest()}.{ext}"
    cle = f"{DOSSIER}/{nom}"
    if stockage_r2.taille_objet(cle) is None:
        stockage_r2.envoyer(cle, octets, mime_final, len(octets))
    return PREFIXE_URL + nom


def contient_images_integrees(html) -> bool:
    return bool(html) and "data:image/" in html


def extraire_images(html):
    """Renvoie le HTML avec ses images base64 remplacées par des liens R2.
    Ne lève jamais d'erreur : en cas de souci, l'image concernée reste intégrée."""
    if not contient_images_integrees(html) or not stockage_r2.r2_actif():
        return html
    deja = {}

    def remplacer(m):
        prefixe, guillemet, mime, donnees = m.group(1), m.group(2), m.group(3).lower(), m.group(4)
        try:
            if donnees not in deja:
                deja[donnees] = _deposer(base64.b64decode(re.sub(r"\s+", "", donnees)), mime)
            return f"{prefixe}{guillemet}{deja[donnees]}{guillemet}"
        except Exception as e:  # noqa: BLE001
            log.error("Image non transférée vers R2 : %s", e)
            return m.group(0)

    return _MOTIF.sub(remplacer, html)


def nom_valide(nom: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{40}\.(webp|png|jpg|gif|svg|bin)", nom or ""))


def url_lecture(nom: str) -> str:
    """URL R2 signée (4 h) pour afficher l'image."""
    return stockage_r2.url_signee(stockage_r2.PREFIXE + f"{DOSSIER}/{nom}")


def reduire_data_uri(valeur: str, cote_max: int = COTE_MAX, seuil: int = 400_000) -> str:
    """Photo de carte collée/choisie en base64 : réduite (1600 px, WebP) si elle est lourde.
    Reste un data URI (affichage inchangé partout), mais ~10 fois plus léger dans Neon."""
    if not valeur or not valeur.startswith("data:image/") or len(valeur) < seuil:
        return valeur
    try:
        entete, _, donnees = valeur.partition(",")
        mime = entete[5:].split(";")[0].lower()
        octets, mime_final = _optimiser(base64.b64decode(donnees), mime)
        nouveau = f"data:{mime_final};base64," + base64.b64encode(octets).decode()
        return nouveau if len(nouveau) < len(valeur) else valeur
    except Exception as e:  # noqa: BLE001
        log.warning("Photo non réduite : %s", e)
        return valeur
