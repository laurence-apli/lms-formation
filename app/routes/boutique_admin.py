"""
Routes admin pour la gestion des tarifs, des codes promo, et de la
présentation (photo + texte) de chaque formation.
À placer dans app/routes/boutique_admin.py (protégées par admin_connecte).
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import obtenir_session
from ..models import Administrateur, Formation
from .auth import admin_connecte
from .boutique_models import TarifFormation, CodePromo

router = APIRouter(prefix="/admin", dependencies=[Depends(admin_connecte)])


# --- Présentation formation (photo + texte) -------------------------------

class PresentationFormationRequete(BaseModel):
    image_url: str | None = None
    description_courte: str | None = None


@router.put("/formations/{formation_id}/presentation")
def modifier_presentation_formation(
    formation_id: int, requete: PresentationFormationRequete, session: Session = Depends(obtenir_session),
):
    formation = session.get(Formation, formation_id)
    if formation is None:
        raise HTTPException(status_code=404, detail="Formation introuvable.")
    if requete.image_url is not None:
        formation.image_url = requete.image_url
    if requete.description_courte is not None:
        formation.description_courte = requete.description_courte
    session.commit()
    return {"ok": True}


# --- Tarifs ------------------------------------------------------------

class TarifRequete(BaseModel):
    formation_id: int
    niveau: int = 1
    nom_option: str = "Tarif unique"
    prix: float
    promo_active: bool = False
    promo_pourcentage: int | None = None
    autoriser_3x: bool = False
    cumulable: bool = False
    ordre: int = 1


@router.get("/formations/{formation_id}/tarifs")
def lire_tarifs(formation_id: int, session: Session = Depends(obtenir_session)):
    tarifs = session.query(TarifFormation).filter_by(formation_id=formation_id).order_by(TarifFormation.ordre).all()
    return [
        {
            "id": t.id, "niveau": t.niveau, "nom_option": t.nom_option, "prix": float(t.prix),
            "promo_active": t.promo_active, "promo_pourcentage": t.promo_pourcentage,
            "autoriser_3x": t.autoriser_3x, "cumulable": t.cumulable, "actif": t.actif,
        }
        for t in tarifs
    ]


@router.post("/tarifs")
def creer_tarif(requete: TarifRequete, session: Session = Depends(obtenir_session)):
    formation = session.get(Formation, requete.formation_id)
    if formation is None:
        raise HTTPException(status_code=404, detail="Formation introuvable.")
    tarif = TarifFormation(**requete.dict())
    session.add(tarif)
    session.commit()
    session.refresh(tarif)
    return {"id": tarif.id}


@router.put("/tarifs/{tarif_id}")
def modifier_tarif(tarif_id: int, requete: TarifRequete, session: Session = Depends(obtenir_session)):
    tarif = session.get(TarifFormation, tarif_id)
    if tarif is None:
        raise HTTPException(status_code=404, detail="Tarif introuvable.")
    for champ, valeur in requete.dict().items():
        setattr(tarif, champ, valeur)
    session.commit()
    return {"ok": True}


@router.delete("/tarifs/{tarif_id}")
def supprimer_tarif(tarif_id: int, session: Session = Depends(obtenir_session)):
    tarif = session.get(TarifFormation, tarif_id)
    if tarif is None:
        raise HTTPException(status_code=404, detail="Tarif introuvable.")
    tarif.actif = False  # désactivation plutôt que suppression -- garde l'historique des ventes cohérent
    session.commit()
    return {"ok": True}


# --- Codes promo ---------------------------------------------------------

class CodePromoRequete(BaseModel):
    code: str
    type_reduction: str
    valeur: float
    reserve_premier_achat: bool = False
    date_fin: str | None = None
    tarif_ids: list[int] = []


@router.get("/codes-promo")
def lire_codes_promo(session: Session = Depends(obtenir_session)):
    codes = session.query(CodePromo).all()
    return [
        {
            "id": c.id, "code": c.code, "type_reduction": c.type_reduction, "valeur": float(c.valeur),
            "actif": c.actif, "reserve_premier_achat": c.reserve_premier_achat,
            "date_fin": c.date_fin.strftime("%d/%m/%Y") if c.date_fin else None,
            "tarif_ids": [t.id for t in c.tarifs_concernes],
        }
        for c in codes
    ]


@router.post("/codes-promo")
def creer_code_promo(requete: CodePromoRequete, session: Session = Depends(obtenir_session)):
    from datetime import datetime
    date_fin = datetime.strptime(requete.date_fin, "%d/%m/%Y") if requete.date_fin else None
    code = CodePromo(
        code=requete.code.strip().upper(), type_reduction=requete.type_reduction, valeur=requete.valeur,
        reserve_premier_achat=requete.reserve_premier_achat, date_fin=date_fin,
    )
    if requete.tarif_ids:
        code.tarifs_concernes = session.query(TarifFormation).filter(TarifFormation.id.in_(requete.tarif_ids)).all()
    session.add(code)
    session.commit()
    return {"id": code.id}


@router.put("/codes-promo/{code_id}")
def modifier_code_promo(code_id: int, requete: CodePromoRequete, session: Session = Depends(obtenir_session)):
    from datetime import datetime
    code = session.get(CodePromo, code_id)
    if code is None:
        raise HTTPException(status_code=404, detail="Code introuvable.")
    code.code = requete.code.strip().upper()
    code.type_reduction = requete.type_reduction
    code.valeur = requete.valeur
    code.reserve_premier_achat = requete.reserve_premier_achat
    code.date_fin = datetime.strptime(requete.date_fin, "%d/%m/%Y") if requete.date_fin else None
    code.tarifs_concernes = session.query(TarifFormation).filter(TarifFormation.id.in_(requete.tarif_ids)).all()
    session.commit()
    return {"ok": True}


@router.post("/codes-promo/{code_id}/toggle")
def activer_desactiver_code(code_id: int, session: Session = Depends(obtenir_session)):
    code = session.get(CodePromo, code_id)
    if code is None:
        raise HTTPException(status_code=404, detail="Code introuvable.")
    code.actif = not code.actif
    session.commit()
    return {"actif": code.actif}


def _tarif_admin_dict(t):
    return {"tarif_id": t.id, "nom_option": t.nom_option, "prix": float(t.prix), "prix_final": t.prix_final(), "en_promo": t.promo_active, "promo_pourcentage": t.promo_pourcentage, "autoriser_3x": t.autoriser_3x, "cumulable": t.cumulable, "niveau": t.niveau, "actif": t.actif}


@router.get("/catalogue-complet")
def lire_catalogue_complet(session: Session = Depends(obtenir_session)):
    formations = session.query(Formation).all()
    resultat = []
    for f in formations:
        tarifs_tries = sorted(f.tarifs, key=lambda t: t.ordre)
        resultat.append({"formation_id": f.id, "titre": f.titre, "actif": f.actif, "image_url": f.image_url, "description_courte": f.description_courte, "tarifs": [_tarif_admin_dict(t) for t in tarifs_tries]})
    return resultat
