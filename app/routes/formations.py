"""
Routes de gestion des formations, modules et chapitres -- réservées à
l'administrateur connecté (toutes les routes dépendent de admin_connecte).
"""
import base64
from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, File, Request
from sqlalchemy.orm import Session

from ..database import obtenir_session
from ..models import (
    Formation, Module, Chapitre, Media, MediaModule, MediaFormation, JoursAccompagnementNiveau,
    SauvegardeMediaBase64, Eleve, AccesFormation,
    dupliquer_chapitre as dupliquer_chapitre_modele,
    dupliquer_formation as dupliquer_formation_modele,
    deplacer_chapitre_vers_module as deplacer_chapitre_modele,
)
from .auth import admin_connecte
from .medias_fichiers import media_json
from .. import stockage_r2

router = APIRouter(prefix="/admin", dependencies=[Depends(admin_connecte)])

# ---------- Formations ----------

@router.get("/formations")
def lister_formations(session: Session = Depends(obtenir_session)):
    formations = session.query(Formation).order_by(Formation.ordre_affichage, Formation.id).all()
    return [
        {
            "id": f.id, "titre": f.titre, "couleur": f.couleur, "actif": f.actif,
            "nb_niveaux": f.nb_niveaux, "ordre_affichage": f.ordre_affichage, "nb_modules": len(f.modules),
            "nb_chapitres": sum(len(m.chapitres) for m in f.modules),
        }
        for f in formations
    ]

@router.get("/formations/{formation_id}")
def detail_formation(formation_id: int, session: Session = Depends(obtenir_session)):
    formation = session.get(Formation, formation_id)
    if formation is None:
        raise HTTPException(status_code=404, detail="Formation introuvable.")
    return {
        "id": formation.id, "titre": formation.titre, "couleur": formation.couleur,
        "actif": formation.actif, "nb_niveaux": formation.nb_niveaux, "ordre_affichage": formation.ordre_affichage,
        "presentation_html": formation.presentation_html or "",
        "medias": [
            media_json("formation", med)
            for med in formation.medias
        ],
        "jours_par_niveau": {j.niveau: j.jours for j in formation.jours_par_niveau},
        "jours_visio_par_niveau": {j.niveau: j.jours_visio for j in formation.jours_par_niveau},
        "lien_visio": formation.lien_visio or "",
        "acces_auto": bool(formation.acces_auto),
        "code_acces_rdv": formation.code_acces_rdv or "",
        "modules": [
            {
                "id": m.id, "titre": m.titre, "ordre": m.ordre, "niveau_requis": m.niveau_requis,
                "presentation_html": m.presentation_html or "",
                "medias": [
                    media_json("module", med)
                    for med in m.medias
                ],
                "chapitres": [
                    {
                        "id": c.id, "titre": c.titre, "ordre": c.ordre, "niveau_requis": c.niveau_requis,
                        "contenu_html": c.contenu_html or "",
                        "lien_coaching": c.lien_coaching or "",
                        "medias": [
                            media_json("chapitre", med)
                            for med in c.medias
                        ],
                    }
                    for c in m.chapitres
                ],
            }
            for m in formation.modules
        ],
    }

@router.post("/formations")
def creer_formation(
    titre: str = Form(...), couleur: str = Form("#B8922A"), nb_niveaux: int = Form(3),
    presentation_html: str = Form(""), ordre_affichage: int = Form(0), session: Session = Depends(obtenir_session),
):
    if nb_niveaux not in (1, 2, 3):
        raise HTTPException(status_code=400, detail="Le nombre de niveaux doit être 1, 2 ou 3.")
    formation = Formation(titre=titre, couleur=couleur, nb_niveaux=nb_niveaux, presentation_html=presentation_html, ordre_affichage=ordre_affichage)
    session.add(formation)
    session.flush()
    for niveau in range(1, nb_niveaux + 1):
        session.add(JoursAccompagnementNiveau(formation_id=formation.id, niveau=niveau, jours=0))
    session.commit()
    return {"id": formation.id, "titre": formation.titre}

@router.put("/formations/{formation_id}")
def modifier_formation(
    formation_id: int, titre: str = Form(...), couleur: str = Form(...),
    nb_niveaux: int = Form(...), presentation_html: str = Form(None),
    ordre_affichage: int = Form(0), lien_visio: str = Form(""),
    acces_auto: bool = Form(False),
    code_acces_rdv: str = Form(""),
    session: Session = Depends(obtenir_session),
):
    formation = session.get(Formation, formation_id)
    if formation is None:
        raise HTTPException(status_code=404, detail="Formation introuvable.")
    if nb_niveaux not in (1, 2, 3):
        raise HTTPException(status_code=400, detail="Le nombre de niveaux doit être 1, 2 ou 3.")

    formation.titre = titre
    formation.couleur = couleur
    # La fenêtre « Modifier la formation » n'envoie pas la présentation : sans ce test,
    # enregistrer le titre ou les séances effaçait la présentation importée.
    if presentation_html is not None:
        formation.presentation_html = presentation_html or None
    formation.ordre_affichage = ordre_affichage
    formation.lien_visio = lien_visio or None
    formation.acces_auto = acces_auto
    formation.code_acces_rdv = code_acces_rdv.strip().lower() or None

    if nb_niveaux != formation.nb_niveaux:
        niveaux_existants = {j.niveau for j in formation.jours_par_niveau}
        for niveau in range(1, nb_niveaux + 1):
            if niveau not in niveaux_existants:
                session.add(JoursAccompagnementNiveau(formation_id=formation.id, niveau=niveau, jours=0))
        formation.nb_niveaux = nb_niveaux

    session.commit()
    return {"id": formation.id, "titre": formation.titre}

@router.post("/formations/{formation_id}/diffuser-a-toutes")
def diffuser_formation_a_toutes(formation_id: int, session: Session = Depends(obtenir_session)):
    """Donne l'accès niveau 1 à cette formation à toutes les élèves actives qui ne l'ont pas encore."""
    formation = session.get(Formation, formation_id)
    if formation is None:
        raise HTTPException(status_code=404, detail="Formation introuvable.")

    # Élèves actives qui n'ont pas encore accès à cette formation
    eleves_avec_acces = {
        a.eleve_id for a in session.query(AccesFormation.eleve_id).filter_by(formation_id=formation_id).all()
    }
    eleves_actives = session.query(Eleve).filter_by(actif=True).all()

    nb_ajouts = 0
    for eleve in eleves_actives:
        if eleve.id not in eleves_avec_acces:
            session.add(AccesFormation(eleve_id=eleve.id, formation_id=formation_id, niveau=1))
            nb_ajouts += 1

    session.commit()
    return {"ok": True, "nb_ajouts": nb_ajouts}


@router.post("/formations/{formation_id}/effacer-html")
def effacer_html_formation(formation_id: int, session: Session = Depends(obtenir_session)):
    """Vide le champ presentation_html d'une formation (retirer un import HTML)."""
    formation = session.get(Formation, formation_id)
    if formation is None:
        raise HTTPException(status_code=404, detail="Formation introuvable.")
    formation.presentation_html = None
    formation.fichier_recu_nom = None
    session.commit()
    return {"ok": True}


@router.put("/formations/{formation_id}/jours-accompagnement")
async def definir_jours_accompagnement(formation_id: int, request: Request, session: Session = Depends(obtenir_session)):
    formation = session.get(Formation, formation_id)
    if formation is None:
        raise HTTPException(status_code=404, detail="Formation introuvable.")
    donnees = await request.form()
    for jpn in formation.jours_par_niveau:
        champ = f"niveau_{jpn.niveau}"
        if champ in donnees:
            jpn.jours = int(donnees[champ])
        champ_visio = f"visio_niveau_{jpn.niveau}"
        if champ_visio in donnees:
            jpn.jours_visio = int(donnees[champ_visio])
    session.commit()
    return {"ok": True}

@router.delete("/formations/{formation_id}")
def supprimer_formation(formation_id: int, session: Session = Depends(obtenir_session)):
    formation = session.get(Formation, formation_id)
    if formation is None:
        raise HTTPException(status_code=404, detail="Formation introuvable.")
    nb_eleves_concernes = len(formation.acces_eleves)
    session.delete(formation)
    session.commit()
    return {"ok": True, "nb_eleves_concernes": nb_eleves_concernes}

@router.post("/formations/{formation_id}/toggle-actif")
def toggle_actif_formation(formation_id: int, session: Session = Depends(obtenir_session)):
    formation = session.get(Formation, formation_id)
    if formation is None:
        raise HTTPException(status_code=404, detail="Formation introuvable.")
    formation.actif = not formation.actif
    session.commit()
    return {"id": formation.id, "actif": formation.actif}

@router.post("/formations/{formation_id}/dupliquer")
def dupliquer_formation(formation_id: int, session: Session = Depends(obtenir_session)):
    formation = session.get(Formation, formation_id)
    if formation is None:
        raise HTTPException(status_code=404, detail="Formation introuvable.")
    copie = dupliquer_formation_modele(session, formation_id)
    return {"id": copie.id, "titre": copie.titre}

# ---------- Modules ----------

@router.post("/formations/{formation_id}/modules")
def creer_module(
    formation_id: int, titre: str = Form(...), niveau_requis: int = Form(1),
    presentation_html: str = Form(""), session: Session = Depends(obtenir_session),
):
    formation = session.get(Formation, formation_id)
    if formation is None:
        raise HTTPException(status_code=404, detail="Formation introuvable.")
    dernier_ordre = session.query(Module).filter_by(formation_id=formation_id).count()
    module = Module(
        formation_id=formation_id, titre=titre,
        niveau_requis=niveau_requis if formation.nb_niveaux > 1 else 1,
        presentation_html=presentation_html, ordre=dernier_ordre + 1,
    )
    session.add(module)
    session.commit()
    return {"id": module.id, "titre": module.titre}

@router.put("/modules/{module_id}")
def modifier_module(
    module_id: int, titre: str = Form(...), niveau_requis: int = Form(1),
    presentation_html: str = Form(""), session: Session = Depends(obtenir_session),
):
    module = session.get(Module, module_id)
    if module is None:
        raise HTTPException(status_code=404, detail="Module introuvable.")
    module.titre = titre
    module.niveau_requis = niveau_requis if module.formation.nb_niveaux > 1 else 1
    module.presentation_html = presentation_html
    session.commit()
    return {"id": module.id, "titre": module.titre}

@router.delete("/modules/{module_id}")
def supprimer_module(module_id: int, session: Session = Depends(obtenir_session)):
    module = session.get(Module, module_id)
    if module is None:
        raise HTTPException(status_code=404, detail="Module introuvable.")
    session.delete(module)
    session.commit()
    return {"ok": True}

@router.post("/modules/{module_id}/deplacer")
def deplacer_module(module_id: int, direction: int = Form(...), session: Session = Depends(obtenir_session)):
    """direction : -1 pour monter, +1 pour descendre."""
    module = session.get(Module, module_id)
    if module is None:
        raise HTTPException(status_code=404, detail="Module introuvable.")
    autres = (
        session.query(Module)
        .filter_by(formation_id=module.formation_id)
        .order_by(Module.ordre)
        .all()
    )
    idx = next(i for i, m in enumerate(autres) if m.id == module.id)
    nouvel_idx = idx + direction
    if 0 <= nouvel_idx < len(autres):
        autres[idx].ordre, autres[nouvel_idx].ordre = autres[nouvel_idx].ordre, autres[idx].ordre
    session.commit()
    return {"ok": True}

# ---------- Chapitres ----------

@router.post("/modules/{module_id}/chapitres")
def creer_chapitre(
    module_id: int, titre: str = Form(...), niveau_requis: int = Form(1),
    lien_coaching: str = Form(""),
    session: Session = Depends(obtenir_session),
):
    module = session.get(Module, module_id)
    if module is None:
        raise HTTPException(status_code=404, detail="Module introuvable.")
    dernier_ordre = (
        session.query(Chapitre)
        .join(Module)
        .filter(Module.formation_id == module.formation_id)
        .count()
    )
    chapitre = Chapitre(
        module_id=module_id, titre=titre,
        niveau_requis=niveau_requis if module.formation.nb_niveaux > 1 else 1,
        ordre=dernier_ordre + 1, contenu_html="",
        lien_coaching=lien_coaching or None,
    )
    session.add(chapitre)
    session.commit()
    return {"id": chapitre.id, "titre": chapitre.titre}

@router.put("/chapitres/{chapitre_id}")
def modifier_chapitre(
    chapitre_id: int, titre: str = Form(...), niveau_requis: int = Form(1),
    lien_coaching: str = Form(""),
    session: Session = Depends(obtenir_session),
):
    chapitre = session.get(Chapitre, chapitre_id)
    if chapitre is None:
        raise HTTPException(status_code=404, detail="Chapitre introuvable.")
    chapitre.titre = titre
    chapitre.niveau_requis = niveau_requis if chapitre.module.formation.nb_niveaux > 1 else 1
    chapitre.lien_coaching = lien_coaching or None
    session.commit()
    return {"id": chapitre.id, "titre": chapitre.titre}

@router.delete("/chapitres/{chapitre_id}")
def supprimer_chapitre(chapitre_id: int, session: Session = Depends(obtenir_session)):
    chapitre = session.get(Chapitre, chapitre_id)
    if chapitre is None:
        raise HTTPException(status_code=404, detail="Chapitre introuvable.")
    session.delete(chapitre)
    session.commit()
    return {"ok": True}

@router.post("/chapitres/{chapitre_id}/dupliquer")
def dupliquer_chapitre(chapitre_id: int, session: Session = Depends(obtenir_session)):
    chapitre = session.get(Chapitre, chapitre_id)
    if chapitre is None:
        raise HTTPException(status_code=404, detail="Chapitre introuvable.")
    copie = dupliquer_chapitre_modele(session, chapitre_id)
    return {"id": copie.id, "titre": copie.titre}

@router.post("/chapitres/{chapitre_id}/deplacer-vers-module")
def deplacer_chapitre_vers_module(
    chapitre_id: int, nouveau_module_id: int = Form(...), session: Session = Depends(obtenir_session),
):
    chapitre = session.get(Chapitre, chapitre_id)
    if chapitre is None:
        raise HTTPException(status_code=404, detail="Chapitre introuvable.")
    try:
        deplacer_chapitre_modele(session, chapitre_id, nouveau_module_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True}

@router.post("/chapitres/{chapitre_id}/deplacer")
def deplacer_chapitre(chapitre_id: int, direction: int = Form(...), session: Session = Depends(obtenir_session)):
    chapitre = session.get(Chapitre, chapitre_id)
    if chapitre is None:
        raise HTTPException(status_code=404, detail="Chapitre introuvable.")
    freres = (
        session.query(Chapitre)
        .filter_by(module_id=chapitre.module_id)
        .order_by(Chapitre.ordre)
        .all()
    )
    idx = next(i for i, c in enumerate(freres) if c.id == chapitre.id)
    nouvel_idx = idx + direction
    if 0 <= nouvel_idx < len(freres):
        freres[idx].ordre, freres[nouvel_idx].ordre = freres[nouvel_idx].ordre, freres[idx].ordre
    session.commit()
    return {"ok": True}

# ---------- Médias ----------

@router.post("/chapitres/{chapitre_id}/medias")
def ajouter_media(
    chapitre_id: int, type: str = Form(...), titre: str = Form(...),
    url: str = Form(...), telechargeable: bool = Form(False),
    session: Session = Depends(obtenir_session),
):
    if type not in ("pdf", "word", "audio", "lien"):
        raise HTTPException(status_code=400, detail="Type de média invalide.")
    chapitre = session.get(Chapitre, chapitre_id)
    if chapitre is None:
        raise HTTPException(status_code=404, detail="Chapitre introuvable.")
    media = Media(chapitre_id=chapitre_id, type=type, titre=titre, url=url, telechargeable=telechargeable)
    session.add(media)
    session.commit()
    return {"id": media.id}

TAILLE_MAX_MEDIA_MO = 30
TAILLE_MAX_MEDIA_OCTETS = TAILLE_MAX_MEDIA_MO * 1024 * 1024
# Sur Cloudflare R2 (si configuré), le fichier ne pèse plus sur Neon : limite plus large
TAILLE_MAX_R2_MO = 300


def _supprimer_r2_si_orphelin(session: Session, url) -> None:
    """Efface le fichier R2 seulement si plus aucun média ne l'utilise
    (une formation ou un chapitre dupliqué partage le même fichier)."""
    if not url:
        return
    for modele in (Media, MediaModule, MediaFormation):
        if session.query(modele.id).filter(modele.url == url).first() is not None:
            return
    stockage_r2.supprimer(url)


async def _stocker_fichier(fichier: UploadFile, mime: str, dossier: str) -> str:
    """Renvoie la valeur à mettre dans media.url : "r2:<clé>" si R2 est configuré
    (fichier envoyé en flux, sans le garder en mémoire), sinon l'ancien data URI base64."""
    taille = fichier.size
    if taille is None:
        fichier.file.seek(0, 2); taille = fichier.file.tell(); fichier.file.seek(0)
    if stockage_r2.r2_actif():
        if taille > TAILLE_MAX_R2_MO * 1024 * 1024:
            raise HTTPException(status_code=400, detail=f"Le fichier est trop volumineux ({TAILLE_MAX_R2_MO} Mo maximum).")
        fichier.file.seek(0)
        cle = stockage_r2.nouvelle_cle(dossier, fichier.filename)
        try:
            from starlette.concurrency import run_in_threadpool
            return await run_in_threadpool(stockage_r2.envoyer, cle, fichier.file, mime, taille)
        except Exception:
            raise HTTPException(status_code=502, detail="L'envoi du fichier vers le stockage a échoué. Réessayez.")
    if taille > TAILLE_MAX_MEDIA_OCTETS:
        raise HTTPException(status_code=400, detail=f"Le fichier est trop volumineux ({TAILLE_MAX_MEDIA_MO} Mo maximum).")
    contenu = await fichier.read()
    return f"data:{mime};base64,{base64.b64encode(contenu).decode('ascii')}"

EXTENSIONS_AUTORISEES = {
    "pdf": {".pdf"},
    "word": {".docx"},
    "audio": {".mp3", ".wav", ".m4a", ".ogg"},
    "video": {".mp4", ".m4v", ".mov", ".webm"},
}
MIME_PAR_EXTENSION = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".mp3": "audio/mpeg", ".wav": "audio/wav",
    ".m4a": "audio/mp4", ".ogg": "audio/ogg",
    ".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm",
}

@router.post("/chapitres/{chapitre_id}/medias/upload")
async def uploader_media_fichier(
    chapitre_id: int, type: str = Form(...), titre: str = Form(...),
    telechargeable: bool = Form(False), fichier: UploadFile = File(...),
    session: Session = Depends(obtenir_session),
):
    if type not in ("pdf", "word", "audio"):
        raise HTTPException(status_code=400, detail="Ce type de média ne s'importe pas par fichier.")
    chapitre = session.get(Chapitre, chapitre_id)
    if chapitre is None:
        raise HTTPException(status_code=404, detail="Chapitre introuvable.")

    extension = "." + fichier.filename.rsplit(".", 1)[-1].lower() if "." in fichier.filename else ""
    if extension not in EXTENSIONS_AUTORISEES.get(type, set()):
        attendu = ", ".join(EXTENSIONS_AUTORISEES.get(type, set()))
        raise HTTPException(status_code=400, detail=f"Format de fichier non reconnu pour ce type (attendu : {attendu}).")

    mime = MIME_PAR_EXTENSION.get(extension, "application/octet-stream")
    data_uri = await _stocker_fichier(fichier, mime, f"medias/chapitre/{chapitre_id}")

    media = Media(chapitre_id=chapitre_id, type=type, titre=titre, url=data_uri, telechargeable=telechargeable)
    session.add(media)
    session.commit()
    return {"id": media.id}

@router.put("/medias/{media_id}/telechargeable")
def toggle_media_telechargeable(media_id: int, telechargeable: bool = Form(...), session: Session = Depends(obtenir_session)):
    media = session.get(Media, media_id)
    if media is None:
        raise HTTPException(status_code=404, detail="Média introuvable.")
    media.telechargeable = telechargeable
    session.commit()
    return {"ok": True}

@router.delete("/medias/{media_id}")
def supprimer_media(media_id: int, session: Session = Depends(obtenir_session)):
    media = session.get(Media, media_id)
    if media is None:
        raise HTTPException(status_code=404, detail="Média introuvable.")
    ancienne_url = media.url if media.est_r2 else None
    session.delete(media)
    session.commit()
    _supprimer_r2_si_orphelin(session, ancienne_url)
    return {"ok": True}


# ---------- Médias module ----------

@router.post("/modules/{module_id}/medias")
def ajouter_media_module(
    module_id: int, type: str = Form(...), titre: str = Form(...),
    url: str = Form(...), telechargeable: bool = Form(False),
    session: Session = Depends(obtenir_session),
):
    if type not in ("pdf", "word", "audio", "lien"):
        raise HTTPException(status_code=400, detail="Type de média invalide.")
    module = session.get(Module, module_id)
    if module is None:
        raise HTTPException(status_code=404, detail="Module introuvable.")
    media = MediaModule(module_id=module_id, type=type, titre=titre, url=url, telechargeable=telechargeable)
    session.add(media)
    session.commit()
    return {"id": media.id}


@router.post("/modules/{module_id}/medias/upload")
async def uploader_media_module(
    module_id: int, type: str = Form(...), titre: str = Form(...),
    telechargeable: bool = Form(False), fichier: UploadFile = File(...),
    session: Session = Depends(obtenir_session),
):
    if type not in ("pdf", "word", "audio"):
        raise HTTPException(status_code=400, detail="Ce type de media ne s'importe pas par fichier.")
    module = session.get(Module, module_id)
    if module is None:
        raise HTTPException(status_code=404, detail="Module introuvable.")
    extension = "." + fichier.filename.rsplit(".", 1)[-1].lower() if "." in fichier.filename else ""
    if extension not in EXTENSIONS_AUTORISEES.get(type, set()):
        attendu = ", ".join(EXTENSIONS_AUTORISEES.get(type, set()))
        raise HTTPException(status_code=400, detail=f"Format non reconnu (attendu : {attendu}).")
    mime = MIME_PAR_EXTENSION.get(extension, "application/octet-stream")
    data_uri = await _stocker_fichier(fichier, mime, f"medias/module/{module_id}")

    media = MediaModule(module_id=module_id, type=type, titre=titre, url=data_uri, telechargeable=telechargeable)
    session.add(media)
    session.commit()
    return {"id": media.id}


@router.put("/medias-module/{media_id}/telechargeable")
def toggle_media_module_telechargeable(media_id: int, telechargeable: bool = Form(...), session: Session = Depends(obtenir_session)):
    media = session.get(MediaModule, media_id)
    if media is None:
        raise HTTPException(status_code=404, detail="Media introuvable.")
    media.telechargeable = telechargeable
    session.commit()
    return {"ok": True}


@router.delete("/medias-module/{media_id}")
def supprimer_media_module(media_id: int, session: Session = Depends(obtenir_session)):
    media = session.get(MediaModule, media_id)
    if media is None:
        raise HTTPException(status_code=404, detail="Media introuvable.")
    ancienne_url = media.url if media.est_r2 else None
    session.delete(media)
    session.commit()
    _supprimer_r2_si_orphelin(session, ancienne_url)
    return {"ok": True}


# ---------- Médias formation ----------

@router.post("/formations/{formation_id}/medias")
def ajouter_media_formation(
    formation_id: int, type: str = Form(...), titre: str = Form(...),
    url: str = Form(...), telechargeable: bool = Form(False),
    session: Session = Depends(obtenir_session),
):
    if type not in ("pdf", "word", "audio", "lien"):
        raise HTTPException(status_code=400, detail="Type de media invalide.")
    formation = session.get(Formation, formation_id)
    if formation is None:
        raise HTTPException(status_code=404, detail="Formation introuvable.")
    media = MediaFormation(formation_id=formation_id, type=type, titre=titre, url=url, telechargeable=telechargeable)
    session.add(media)
    session.commit()
    return {"id": media.id}


@router.post("/formations/{formation_id}/medias/upload")
async def uploader_media_formation(
    formation_id: int, type: str = Form(...), titre: str = Form(...),
    telechargeable: bool = Form(False), fichier: UploadFile = File(...),
    session: Session = Depends(obtenir_session),
):
    if type not in ("pdf", "word", "audio"):
        raise HTTPException(status_code=400, detail="Ce type de media ne s'importe pas par fichier.")
    formation = session.get(Formation, formation_id)
    if formation is None:
        raise HTTPException(status_code=404, detail="Formation introuvable.")
    extension = "." + fichier.filename.rsplit(".", 1)[-1].lower() if "." in fichier.filename else ""
    if extension not in EXTENSIONS_AUTORISEES.get(type, set()):
        attendu = ", ".join(EXTENSIONS_AUTORISEES.get(type, set()))
        raise HTTPException(status_code=400, detail=f"Format non reconnu (attendu : {attendu}).")
    mime = MIME_PAR_EXTENSION.get(extension, "application/octet-stream")
    data_uri = await _stocker_fichier(fichier, mime, f"medias/formation/{formation_id}")

    media = MediaFormation(formation_id=formation_id, type=type, titre=titre, url=data_uri, telechargeable=telechargeable)
    session.add(media)
    session.commit()
    return {"id": media.id}


@router.put("/medias-formation/{media_id}/telechargeable")
def toggle_media_formation_telechargeable(media_id: int, telechargeable: bool = Form(...), session: Session = Depends(obtenir_session)):
    media = session.get(MediaFormation, media_id)
    if media is None:
        raise HTTPException(status_code=404, detail="Media introuvable.")
    media.telechargeable = telechargeable
    session.commit()
    return {"ok": True}


@router.delete("/medias-formation/{media_id}")
def supprimer_media_formation(media_id: int, session: Session = Depends(obtenir_session)):
    media = session.get(MediaFormation, media_id)
    if media is None:
        raise HTTPException(status_code=404, detail="Media introuvable.")
    ancienne_url = media.url if media.est_r2 else None
    session.delete(media)
    session.commit()
    _supprimer_r2_si_orphelin(session, ancienne_url)
    return {"ok": True}


# ---------- Vérification du stockage Cloudflare R2 ----------

@router.get("/stockage-r2/verifier")
def verifier_stockage_r2():
    """Dépose, relit puis efface un petit fichier test : confirme que les clés R2 de Render fonctionnent."""
    if not stockage_r2.r2_actif():
        return {"actif": False, "message": "Variables R2_… absentes sur Render : les fichiers restent dans la base."}
    cle = "verification/test.txt"
    try:
        stockage_r2.envoyer(cle, b"ok", "text/plain", 2)
        taille = stockage_r2.taille_objet(cle)
        stockage_r2.supprimer(stockage_r2.PREFIXE + cle)
    except Exception as e:  # noqa: BLE001
        return {"actif": True, "ok": False, "message": str(e)}
    return {"actif": True, "ok": taille == 2, "bucket": stockage_r2.R2_BUCKET}



# ---------- Transfert des médias base64 (Neon) vers R2 ----------

_MODELES_MEDIAS = {"chapitre": Media, "module": MediaModule, "formation": MediaFormation}


def _formation_titre(nature, media):
    try:
        if nature == "chapitre":
            return media.chapitre.module.formation.titre
        if nature == "module":
            return media.module.formation.titre
        return media.formation.titre
    except Exception:  # noqa: BLE001
        return ""


@router.get("/stockage-r2/inventaire")
def inventaire_medias(session: Session = Depends(obtenir_session)):
    """Médias encore en base64 dans Neon, déjà sur R2, et copies de sécurité restantes."""
    restants, sur_r2 = [], 0
    for nature, modele in _MODELES_MEDIAS.items():
        for m in session.query(modele).all():
            if m.est_r2:
                sur_r2 += 1
            elif m.est_integre:
                restants.append({"nature": nature, "id": m.id, "type": m.type, "titre": m.titre,
                                 "formation": _formation_titre(nature, m),
                                 "octets": int((m.taille_texte or 0) * 3 / 4)})
    restants.sort(key=lambda x: x["octets"])
    return {"r2_actif": stockage_r2.r2_actif(), "restants": restants, "deja_sur_r2": sur_r2,
            "sauvegardes": session.query(SauvegardeMediaBase64).count()}


@router.post("/stockage-r2/migrer/{nature}/{media_id}")
def migrer_media_vers_r2(nature: str, media_id: int, session: Session = Depends(obtenir_session)):
    """Envoie UN média base64 sur R2, vérifie taille + MD5, garde une copie de sécurité,
    puis seulement fait pointer le média vers R2."""
    import hashlib
    import re as _re
    if not stockage_r2.r2_actif():
        raise HTTPException(status_code=400, detail="R2 non configuré.")
    modele = _MODELES_MEDIAS.get(nature)
    media = session.get(modele, media_id) if modele else None
    if media is None:
        raise HTTPException(status_code=404, detail="Média introuvable.")
    if not media.est_integre:
        return {"ok": True, "deja": True}
    ancienne = media.url
    m = _re.match(r"^data:([^;,]*)(;[^,]*)?,", ancienne[:300])
    if m is None:
        raise HTTPException(status_code=500, detail="Data URI illisible.")
    mime = m.group(1) or "application/octet-stream"
    contenu = base64.b64decode(ancienne[m.end():])
    md5 = hashlib.md5(contenu).hexdigest()
    ext = {v: k for k, v in MIME_PAR_EXTENSION.items()}.get(mime, "")
    cle = stockage_r2.nouvelle_cle(f"medias/{nature}/{_dossier_id(nature, media)}", (media.titre or "fichier") + ext)
    nouvelle = stockage_r2.envoyer(cle, contenu, mime, len(contenu))
    taille, etag = stockage_r2.infos_objet(cle)
    if taille != len(contenu) or etag != md5:
        stockage_r2.supprimer(nouvelle)
        raise HTTPException(status_code=500, detail=f"Vérification échouée (taille {taille}/{len(contenu)}, md5 {etag}/{md5}).")
    session.add(SauvegardeMediaBase64(nature=nature, media_id=media.id, ancienne_url=ancienne, nouvelle_url=nouvelle))
    media.url = nouvelle
    session.commit()
    return {"ok": True, "octets": len(contenu), "md5": md5, "cle": cle}


def _dossier_id(nature, media):
    return {"chapitre": media.chapitre_id if nature == "chapitre" else None,
            "module": getattr(media, "module_id", None),
            "formation": getattr(media, "formation_id", None)}[nature]


@router.post("/stockage-r2/restaurer/{nature}/{media_id}")
def restaurer_media_base64(nature: str, media_id: int, session: Session = Depends(obtenir_session)):
    """Retour arrière : remet le fichier base64 d'origine (l'objet R2 reste, sans gêne)."""
    modele = _MODELES_MEDIAS.get(nature)
    media = session.get(modele, media_id) if modele else None
    sauvegarde = (session.query(SauvegardeMediaBase64).filter_by(nature=nature, media_id=media_id)
                  .order_by(SauvegardeMediaBase64.id.desc()).first())
    if media is None or sauvegarde is None:
        raise HTTPException(status_code=404, detail="Rien à restaurer.")
    media.url = sauvegarde.ancienne_url
    if not media.url.startswith(("data:", stockage_r2.PREFIXE)):
        media.type = "lien"  # c'était un lien externe (ex. YouTube) avant le remplacement
    session.commit()
    return {"ok": True}


@router.post("/stockage-r2/purger-sauvegardes")
def purger_sauvegardes(session: Session = Depends(obtenir_session)):
    """À lancer une fois la lecture depuis R2 testée : libère la place dans Neon."""
    n = session.query(SauvegardeMediaBase64).delete()
    session.commit()
    return {"ok": True, "supprimees": n}



# ---------- Dépôt direct navigateur -> R2 (vidéos, gros fichiers) ----------
# 1) /admin/televersement/preparer donne une URL de dépôt signée (le fichier ne passe pas par Render)
# 2) le navigateur envoie le fichier (PUT) avec une barre de progression
# 3) /admin/medias-r2/{nature}/{parent_id} crée le média, ou /admin/medias-r2/remplacer/{nature}/{id}
#    remplace le fichier d'un média existant (ex. un lien YouTube devient une vidéo hébergée)

TAILLE_MAX_DEPOT_MO = 1024
_PARENTS = {"chapitre": Chapitre, "module": Module, "formation": Formation}


def _verifier_extension(type_media: str, nom_fichier: str) -> str:
    extension = "." + nom_fichier.rsplit(".", 1)[-1].lower() if "." in nom_fichier else ""
    if extension not in EXTENSIONS_AUTORISEES.get(type_media, set()):
        attendu = ", ".join(sorted(EXTENSIONS_AUTORISEES.get(type_media, set())))
        raise HTTPException(status_code=400, detail=f"Format non reconnu pour ce type (attendu : {attendu}).")
    return extension


@router.post("/televersement/preparer")
async def preparer_televersement(request: Request, session: Session = Depends(obtenir_session)):
    if not stockage_r2.r2_actif():
        raise HTTPException(status_code=409, detail="R2 non configuré.")
    d = await request.json()
    nature, parent_id = d.get("nature"), int(d.get("parent_id") or 0)
    nom, type_media, taille = str(d.get("nom_fichier") or ""), d.get("type"), int(d.get("taille") or 0)
    modele = _PARENTS.get(nature)
    if modele is None or session.get(modele, parent_id) is None:
        raise HTTPException(status_code=404, detail="Emplacement introuvable.")
    extension = _verifier_extension(type_media, nom)
    if taille <= 0 or taille > TAILLE_MAX_DEPOT_MO * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"Fichier vide ou trop volumineux ({TAILLE_MAX_DEPOT_MO} Mo maximum).")
    cle = stockage_r2.nouvelle_cle(f"medias/{nature}/{parent_id}", nom)
    return {"cle": cle, "url": stockage_r2.url_depot(cle),
            "type_mime": MIME_PAR_EXTENSION.get(extension, "application/octet-stream")}


def _verifier_depot(nature: str, parent_id: int, cle: str) -> str:
    if not cle.startswith(f"medias/{nature}/{parent_id}/") or ".." in cle:
        raise HTTPException(status_code=400, detail="Clé de fichier invalide.")
    taille, _ = stockage_r2.infos_objet(cle)
    if not taille:
        raise HTTPException(status_code=400, detail="Le fichier n'est pas arrivé sur le stockage. Réessayez.")
    return stockage_r2.PREFIXE + cle


@router.post("/medias-r2/{nature}/{parent_id}")
async def creer_media_depuis_r2(nature: str, parent_id: int, request: Request,
                                session: Session = Depends(obtenir_session)):
    d = await request.json()
    type_media, titre = d.get("type"), (d.get("titre") or "").strip()
    if type_media not in EXTENSIONS_AUTORISEES or not titre:
        raise HTTPException(status_code=400, detail="Type ou titre manquant.")
    modele_parent = _PARENTS.get(nature)
    if modele_parent is None or session.get(modele_parent, parent_id) is None:
        raise HTTPException(status_code=404, detail="Emplacement introuvable.")
    url = _verifier_depot(nature, parent_id, str(d.get("cle") or ""))
    champ = {"chapitre": "chapitre_id", "module": "module_id", "formation": "formation_id"}[nature]
    media = _MODELES_MEDIAS[nature](**{champ: parent_id}, type=type_media, titre=titre[:200], url=url,
                                     telechargeable=bool(d.get("telechargeable")))
    session.add(media)
    session.commit()
    return {"id": media.id}


@router.post("/medias-r2/remplacer/{nature}/{media_id}")
async def remplacer_fichier_media(nature: str, media_id: int, request: Request,
                                  session: Session = Depends(obtenir_session)):
    """Remplace le contenu d'un média existant (même titre, même place) par un fichier
    déposé sur R2. L'ancienne valeur (lien YouTube, base64…) est gardée en sauvegarde."""
    d = await request.json()
    type_media = d.get("type")
    if type_media not in EXTENSIONS_AUTORISEES:
        raise HTTPException(status_code=400, detail="Type invalide.")
    modele = _MODELES_MEDIAS.get(nature)
    media = session.get(modele, media_id) if modele else None
    if media is None:
        raise HTTPException(status_code=404, detail="Média introuvable.")
    url = _verifier_depot(nature, _dossier_id(nature, media), str(d.get("cle") or ""))
    ancienne = media.url
    session.add(SauvegardeMediaBase64(nature=nature, media_id=media.id, ancienne_url=ancienne, nouvelle_url=url))
    media.url = url
    media.type = type_media
    session.commit()
    return {"ok": True}
