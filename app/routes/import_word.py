"""
Route d'import Word -- enfin BRANCHÉE pour de vrai sur le moteur déjà testé
(word_to_web.py), contrairement à la maquette qui ne pouvait que simuler ce
geste (un navigateur ne peut pas exécuter de Python).

Le fichier déposé par l'administratrice est traité immédiatement et son
contenu HTML résultant est stocké directement sur l'entité concernée
(formation, module ou chapitre) -- plus de simulation, plus de "fichier reçu"
sans suite.
"""
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException
from sqlalchemy.orm import Session

from ..database import obtenir_session
from ..models import Formation, Module, Chapitre
from ..word_to_web import importer_word_depuis_bytes
from .auth import admin_connecte

router = APIRouter(prefix="/admin", dependencies=[Depends(admin_connecte)])

TAILLE_MAX_OCTETS = 4 * 1024 * 1024  # 4 Mo -- volontairement prudent : le traitement d'un
# fichier Word peut consommer jusqu'à ~50 fois sa taille en mémoire pendant l'import (mesuré),
# et le plan gratuit de Render ne dispose que de 512 Mo de RAM au total pour tout le serveur.
# Largement suffisant pour un chapitre avec quelques images de bonne qualité (quelques Mo en
# tout) -- si Laurence a besoin d'importer un document vraiment plus lourd, mieux vaut le
# découper en plusieurs chapitres (ce qui est de toute façon la bonne pratique pédagogique).


def _verifier_fichier_word(fichier: UploadFile) -> None:
    if not fichier.filename.lower().endswith(".docx"):
        raise HTTPException(status_code=400, detail="Seuls les fichiers .docx sont acceptés.")


async def _lire_et_importer(fichier: UploadFile) -> str:
    _verifier_fichier_word(fichier)
    contenu = await fichier.read()
    if len(contenu) > TAILLE_MAX_OCTETS:
        raise HTTPException(status_code=400, detail="Le fichier est trop volumineux (4 Mo maximum). Pour un document plus long, pense à le découper en plusieurs chapitres.")
    try:
        return importer_word_depuis_bytes(contenu)
    except Exception as e:
        # On ne renvoie jamais le détail technique brut à l'écran -- mais on
        # le garde en tête pour le journal serveur (utile en cas de bug réel).
        raise HTTPException(
            status_code=400,
            detail="Le fichier n'a pas pu être lu. Vérifiez qu'il s'agit bien d'un document Word valide (.docx).",
        ) from e


@router.post("/formations/{formation_id}/importer-word")
async def importer_word_formation(
    formation_id: int, fichier: UploadFile = File(...), session: Session = Depends(obtenir_session),
):
    formation = session.get(Formation, formation_id)
    if formation is None:
        raise HTTPException(status_code=404, detail="Formation introuvable.")

    html_resultat = await _lire_et_importer(fichier)
    formation.presentation_html = html_resultat
    formation.fichier_recu_nom = fichier.filename
    session.commit()
    return {"ok": True, "fichier": fichier.filename, "taille_html": len(html_resultat)}


@router.post("/modules/{module_id}/importer-word")
async def importer_word_module(
    module_id: int, fichier: UploadFile = File(...), session: Session = Depends(obtenir_session),
):
    module = session.get(Module, module_id)
    if module is None:
        raise HTTPException(status_code=404, detail="Module introuvable.")

    html_resultat = await _lire_et_importer(fichier)
    module.presentation_html = html_resultat
    module.fichier_recu_nom = fichier.filename
    session.commit()
    return {"ok": True, "fichier": fichier.filename, "taille_html": len(html_resultat)}


@router.post("/chapitres/{chapitre_id}/importer-word")
async def importer_word_chapitre(
    chapitre_id: int, fichier: UploadFile = File(...), session: Session = Depends(obtenir_session),
):
    chapitre = session.get(Chapitre, chapitre_id)
    if chapitre is None:
        raise HTTPException(status_code=404, detail="Chapitre introuvable.")

    html_resultat = await _lire_et_importer(fichier)
    chapitre.contenu_html = html_resultat
    chapitre.fichier_recu_nom = fichier.filename
    session.commit()
    return {"ok": True, "fichier": fichier.filename, "taille_html": len(html_resultat)}


async def _lire_html(fichier: UploadFile) -> str:
    """Lit un fichier .html et retourne le contenu brut -- affiché en iframe isolée côté élève."""
    if not fichier.filename.lower().endswith(".html"):
        raise HTTPException(status_code=400, detail="Seuls les fichiers .html sont acceptés.")
    contenu = await fichier.read()
    if len(contenu) > TAILLE_MAX_OCTETS:
        raise HTTPException(status_code=400, detail="Le fichier est trop volumineux (4 Mo max).")
    return contenu.decode("utf-8", errors="replace")


@router.post("/chapitres/{chapitre_id}/importer-html")
async def importer_html_chapitre(
    chapitre_id: int, fichier: UploadFile = File(...), session: Session = Depends(obtenir_session)
):
    chapitre = session.get(Chapitre, chapitre_id)
    if chapitre is None:
        raise HTTPException(status_code=404, detail="Chapitre introuvable.")
    html_resultat = await _lire_html(fichier)
    chapitre.contenu_html = html_resultat
    chapitre.fichier_recu_nom = fichier.filename
    session.commit()
    return {"ok": True, "fichier": fichier.filename, "taille_html": len(html_resultat)}


@router.post("/formations/{formation_id}/importer-html")
async def importer_html_formation(
    formation_id: int, fichier: UploadFile = File(...), session: Session = Depends(obtenir_session)
):
    formation = session.get(Formation, formation_id)
    if formation is None:
        raise HTTPException(status_code=404, detail="Formation introuvable.")
    html_resultat = await _lire_html(fichier)
    formation.presentation_html = html_resultat
    formation.fichier_recu_nom = fichier.filename
    session.commit()
    return {"ok": True, "fichier": fichier.filename, "taille_html": len(html_resultat)}


@router.post("/modules/{module_id}/importer-html")
async def importer_html_module(
    module_id: int, fichier: UploadFile = File(...), session: Session = Depends(obtenir_session)
):
    module = session.get(Module, module_id)
    if module is None:
        raise HTTPException(status_code=404, detail="Module introuvable.")
    html_resultat = await _lire_html(fichier)
    module.presentation_html = html_resultat
    module.fichier_recu_nom = fichier.filename
    session.commit()
    return {"ok": True, "fichier": fichier.filename, "taille_html": len(html_resultat)}
