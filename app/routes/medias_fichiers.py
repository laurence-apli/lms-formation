"""Service des fichiers médias (audio, PDF) stockés en base sous forme de data URI base64.

Avant : chaque liste de médias (admin et élève) renvoyait le fichier complet dans le JSON.
Une formation avec plusieurs audios de 20-30 Mo faisait dépasser les 512 Mo de mémoire
du serveur Render gratuit -> plantage et erreur 503.

Maintenant : les listes renvoient une petite URL (/medias/<type>/<id>/fichier) et le
fichier n'est décodé que lorsqu'il est réellement lu ou téléchargé, un à la fois.
Les liens externes (YouTube, Drive…) sont renvoyés tels quels.
"""
import base64
import binascii
import re

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from ..database import obtenir_session
from ..models import Administrateur, Eleve, Media, MediaModule, MediaFormation, ValidationChapitre, chapitre_est_accessible

router = APIRouter()

MODELES = {"chapitre": Media, "module": MediaModule, "formation": MediaFormation}
_ENTETE = re.compile(r"^data:([^;,]*)(;[^,]*)?,")


def url_media(nature: str, media) -> str:
    """URL à envoyer au navigateur, sans jamais charger le fichier base64."""
    if media.est_integre:
        return f"/medias/{nature}/{media.id}/fichier"
    return media.url  # lien externe : quelques octets


def media_json(nature: str, media) -> dict:
    return {"id": media.id, "type": media.type, "titre": media.titre,
            "url": url_media(nature, media), "telechargeable": media.telechargeable}


def _formation_du_media(nature: str, media):
    if nature == "chapitre":
        return media.chapitre.module.formation
    if nature == "module":
        return media.module.formation
    return media.formation


def _verifier_droits(request: Request, nature: str, media, session: Session) -> None:
    admin_id = request.session.get("admin_id")
    if admin_id is not None and session.get(Administrateur, admin_id) is not None:
        return
    eleve_id = request.session.get("eleve_id")
    eleve = session.get(Eleve, eleve_id) if eleve_id is not None else None
    if eleve is None:
        raise HTTPException(status_code=401, detail="Connexion requise.")
    # Mêmes règles que les routes élève qui donnaient auparavant le fichier
    from .espace_eleve import _verifier_acces_formation
    _verifier_acces_formation(eleve, _formation_du_media(nature, media), session)
    if nature == "chapitre":
        ok, _ = chapitre_est_accessible(session, eleve.id, media.chapitre)
        deja_valide = session.query(ValidationChapitre).filter_by(
            eleve_id=eleve.id, chapitre_id=media.chapitre_id).first() is not None
        if not ok and not deja_valide:
            raise HTTPException(status_code=403, detail="Chapitre non accessible.")


@router.get("/medias/{nature}/{media_id}/fichier")
def fichier_media(nature: str, media_id: int, request: Request, session: Session = Depends(obtenir_session)):
    modele = MODELES.get(nature)
    if modele is None:
        raise HTTPException(status_code=404, detail="Média introuvable.")
    media = session.get(modele, media_id)
    if media is None:
        raise HTTPException(status_code=404, detail="Média introuvable.")
    _verifier_droits(request, nature, media, session)

    url = media.url
    if not url.startswith("data:"):
        return Response(status_code=307, headers={"Location": url})
    m = _ENTETE.match(url[:300])
    if m is None:
        raise HTTPException(status_code=500, detail="Fichier illisible.")
    mime = m.group(1) or "application/octet-stream"
    try:
        contenu = base64.b64decode(url[m.end():])
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=500, detail="Fichier illisible.")
    del url
    total = len(contenu)

    entetes = {"Accept-Ranges": "bytes", "Cache-Control": "private, max-age=86400",
               "Content-Disposition": "inline"}
    # Range : indispensable pour avancer dans un audio (et pour Safari / iPhone)
    plage = request.headers.get("range", "")
    mr = re.match(r"bytes=(\d*)-(\d*)$", plage.strip())
    if mr and total:
        debut_s, fin_s = mr.groups()
        if debut_s == "":
            debut = max(0, total - int(fin_s or 0))
            fin = total - 1
        else:
            debut = int(debut_s)
            fin = min(int(fin_s), total - 1) if fin_s else total - 1
        if debut >= total or debut > fin:
            return Response(status_code=416, headers={"Content-Range": f"bytes */{total}"})
        entetes["Content-Range"] = f"bytes {debut}-{fin}/{total}"
        return Response(content=contenu[debut:fin + 1], status_code=206, media_type=mime, headers=entetes)
    return Response(content=contenu, media_type=mime, headers=entetes)
