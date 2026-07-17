"""
Routes publiques/élève de la boutique -- catalogue, aperçu panier, et
propositions de montée en niveau.

À placer dans app/routes/boutique_public.py
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import obtenir_session
from ..models import Formation, Eleve
from .boutique_models import calculer_panier, propositions_montee_niveau
from .auth import eleve_connecte

router = APIRouter()

@router.get("/public/catalogue")
def lire_catalogue(session: Session = Depends(obtenir_session)):
    """Renvoie toutes les formations actives avec leurs tarifs, photo et
    description -- c'est cette route que le site vitrine et le catalogue
    élève appellent pour tout afficher, toujours à jour."""
    formations = session.query(Formation).filter_by(actif=True).order_by(Formation.ordre_affichage, Formation.id).all()
    resultat = []
    for f in formations:
        tarifs = [t for t in f.tarifs if t.actif]
        if not tarifs:
            continue
        resultat.append({
            "formation_id": f.id,
            "titre": f.titre,
            "image_url": f.image_url,
            "description_courte": f.description_courte,
            "tarifs": [
                {
                    "tarif_id": t.id,
                    "nom_option": t.nom_option,
                    "prix": float(t.prix),
                    "prix_final": t.prix_final(),
                    "en_promo": t.promo_active,
                    "autoriser_3x": t.autoriser_3x,
                    "cumulable": t.cumulable,
                    "niveau": t.niveau,
                    "contenu_ajoute": t.contenu_ajoute,
                }
                for t in sorted(tarifs, key=lambda t: t.ordre)
            ],
        })
    return resultat

class ApercuPanierRequete(BaseModel):
    tarif_ids: list[int] = []
    montee_tarif_ids: list[int] = []
    code_promo: str | None = None

@router.post("/eleve/panier/apercu")
def apercu_panier(
    requete: ApercuPanierRequete,
    eleve: Eleve = Depends(eleve_connecte),
    session: Session = Depends(obtenir_session),
):
    """Calcule le récapitulatif du panier -- mêmes règles de calcul que la
    vraie création de paiement, pour ne jamais afficher un prix différent
    de ce qui sera réellement facturé. Le panier peut mélanger des achats
    neufs (tarif_ids) et des montées de niveau (montee_tarif_ids)."""
    if not requete.tarif_ids and not requete.montee_tarif_ids:
        return {"lignes": [], "total": 0, "code_applique": None, "erreur_code": None, "trois_x_disponible": False}
    return calculer_panier(session, requete.tarif_ids, requete.code_promo, eleve.id, requete.montee_tarif_ids)

@router.get("/eleve/montees-de-niveau")
def lire_montees_de_niveau(eleve: Eleve = Depends(eleve_connecte), session: Session = Depends(obtenir_session)):
    """Renvoie les propositions de montée en niveau pour l'élève connecté --
    consommé à la fois par le tableau de bord et par le catalogue."""
    return propositions_montee_niveau(session, eleve.id)
