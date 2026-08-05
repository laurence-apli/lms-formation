"""
Routes de gestion des formations, modules et chapitres -- rÃ©servÃ©es Ã 
l'administrateur connectÃ© (toutes les routes dÃ©pendent de admin_connecte).
"""
import base64
from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, File, Request
from sqlalchemy.orm import Session

from ..database import obtenir_session
from ..models import (
    Formation, Module, Chapitre, Media, JoursAccompagnementNiveau,
    dupliquer_chapitre as dupliquer_chapitre_modele,
    dupliquer_formation as dupliquer_formation_modele,
    deplacer_chapitre_vers_module as deplacer_chapitre_modele,
)
from .auth import admin_connecte

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
        "jours_par_niveau": {j.niveau: j.jours for j in formation.jours_par_niveau},
        "jours_visio_par_niveau": {j.niveau: j.jours_visio for j in formation.jours_par_niveau},
        "lien_visio": formation.lien_visio or "",
        "modules": [
            {
                "id": m.id, "titre": m.titre, "niveau_requis": m.niveau_requis,
                "presentation_html": m.presentation_html or "",
                "chapitres": [
                    {
                        "id": c.id, "titre": c.titre, "niveau_requis": c.niveau_requis,
                        "contenu_html": c.contenu_html or "",
                        "lien_coaching": c.lien_coaching or "",
                        "medias": [
                            {"id": med.id, "type": med.type, "titre": med.titre,
                             "url": med.url, "telechargeable": med.telechargeable}
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
        raise HTTPException(status_code=400, detail="Le nombre de niveaux doit Ãªtre 1, 2 ou 3.")
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
    nb_niveaux: int = Form(...), presentation_html: str = Form(""),
    ordre_affichage: int = Form(0), lien_visio: str = Form(""),
    session: Session = Depends(obtenir_session),
):
    formation = session.get(Formation, formation_id)
    if formation is None:
        raise HTTPException(status_code=404, detail="Formation introuvable.")
    if nb_niveaux not in (1, 2, 3):
        raise HTTPException(status_code=400, detail="Le nombre de niveaux doit Ãªtre 1, 2 ou 3.")

    formation.titre = titre
    formation.couleur = couleur
    formation.presentation_html = presentation_html
    formation.ordre_affichage = ordre_affichage
    formation.lien_visio = lien_visio or None

    if nb_niveaux != formation.nb_niveaux:
        niveaux_existants = {j.niveau for j in formation.jours_par_niveau}
        for niveau in range(1, nb_niveaux + 1):
            if niveau not in niveaux_existants:
                session.add(JoursAccompagnementNiveau(formation_id=formation.id, niveau=niveau, jours=0))
        formation.nb_niveaux = nb_niveaux

    session.commit()
    return {"id": formation.id, "titre": formation.titre}

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

# ---------- MÃ©dias ----------

@router.post("/chapitres/{chapitre_id}/medias")
def ajouter_media(
    chapitre_id: int, type: str = Form(...), titre: str = Form(...),
    url: str = Form(...), telechargeable: bool = Form(False),
    session: Session = Depends(obtenir_session),
):
    if type not in ("pdf", "audio", "lien"):
        raise HTTPException(status_code=400, detail="Type de mÃ©dia invalide.")
    chapitre = session.get(Chapitre, chapitre_id)
    if chapitre is None:
        raise HTTPException(status_code=404, detail="Chapitre introuvable.")
    media = Media(chapitre_id=chapitre_id, type=type, titre=titre, url=url, telechargeable=telechargeable)
    session.add(media)
    session.commit()
    return {"id": media.id}

TAILLE_MAX_MEDIA_OCTETS = 25 * 1024 * 1024

EXTENSIONS_AUTORISEES = {
    "pdf": {".pdf"},
    "audio": {".mp3", ".wav", ".m4a", ".ogg"},
}
MIME_PAR_EXTENSION = {
    ".pdf": "application/pdf", ".mp3": "audio/mpeg", ".wav": "audio/wav",
    ".m4a": "audio/mp4", ".ogg": "audio/ogg",
}

@router.post("/chapitres/{chapitre_id}/medias/upload")
async def uploader_media_fichier(
    chapitre_id: int, type: str = Form(...), titre: str = Form(...),
    telechargeable: bool = Form(False), fichier: UploadFile = File(...),
    session: Session = Depends(obtenir_session),
):
    if type not in ("pdf", "audio"):
        raise HTTPException(status_code=400, detail="Ce type de mÃ©dia ne s'importe pas par fichier.")
    chapitre = session.get(Chapitre, chapitre_id)
    if chapitre is None:
        raise HTTPException(status_code=404, detail="Chapitre introuvable.")

    extension = "." + fichier.filename.rsplit(".", 1)[-1].lower() if "." in fichier.filename else ""
    if extension not in EXTENSIONS_AUTORISEES.get(type, set()):
        attendu = ", ".join(EXTENSIONS_AUTORISEES.get(type, set()))
        raise HTTPException(status_code=400, detail=f"Format de fichier non reconnu pour ce type (attendu : {attendu}).")

    contenu = await fichier.read()
    if len(contenu) > TAILLE_MAX_MEDIA_OCTETS:
        raise HTTPException(status_code=400, detail="Le fichier est trop volumineux (8 Mo maximum).")

    mime = MIME_PAR_EXTENSION.get(extension, "application/octet-stream")
    data_uri = f"data:{mime};base64,{base64.b64encode(contenu).decode('ascii')}"

    media = Media(chapitre_id=chapitre_id, type=type, titre=titre, url=data_uri, telechargeable=telechargeable)
    session.add(media)
    session.commit()
    return {"id": media.id}

@router.put("/medias/{media_id}/telechargeable")
def toggle_media_telechargeable(media_id: int, telechargeable: bool = Form(...), session: Session = Depends(obtenir_session)):
    media = session.get(Media, media_id)
    if media is None:
        raise HTTPException(status_code=404, detail="MÃ©dia introuvable.")
    media.telechargeable = telechargeable
    session.commit()
    return {"ok": True}

@router.delete("/medias/{media_id}")
def supprimer_media(media_id: int, session: Session = Depends(obtenir_session)):
    media = session.get(Media, media_id)
    if media is None:
        raise HTTPException(status_code=404, detail="MÃ©dia introuvable.")
    session.delete(media)
    session.commit()
    return {"ok": True}
