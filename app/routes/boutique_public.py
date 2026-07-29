"""
Routes publiques/élève de la boutique -- catalogue, aperçu panier, et
propositions de montée en niveau.

À placer dans app/routes/boutique_public.py
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
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
        resultat.append({
            "id": f.id,
            "titre": f.titre,
            "description_courte": f.description_courte,
            "image_url": f.image_url,
            "tarifs": [
                {
                    "id": t.id,
                    "nom_option": t.nom_option,
                    "prix_base": float(t.prix),
                    "remise_pourcent": t.promo_pourcentage if t.promo_active else 0,
                    "remise_montant": round(float(t.prix) - float(t.prix_final()), 2),
                    "prix_final": float(t.prix_final()),
                }
                for t in tarifs
            ],
        })
    return resultat


class ArticlesPanier(BaseModel):
    articles: list[dict]  # [{tarif_id: int, quantite: int}]


@router.post("/public/apercu-panier")
def apercu_panier(body: ArticlesPanier, session: Session = Depends(obtenir_session)):
    """Calcule le montant total d'un panier sans créer de commande.
    Utilisé par le tunnel de paiement côté client pour afficher les totaux."""
    return calculer_panier(body.articles, session)


@router.get("/public/formations/{formation_id}/montee-niveau")
def monter_niveau(
    formation_id: int,
    eleve: Eleve = Depends(eleve_connecte),
    session: Session = Depends(obtenir_session),
):
    """Retourne les propositions de passage au niveau supérieur pour un élève
    sur une formation donnée -- formations plus complètes, avec le delta à payer."""
    formation = session.get(Formation, formation_id)
    if not formation:
        raise HTTPException(status_code=404, detail="Formation introuvable")
    return propositions_montee_niveau(eleve, formation, session)


@router.get("/api/tarifs-site")
def tarifs_site(session: Session = Depends(obtenir_session)):
    """Endpoint public CORS pour le site vitrine — retourne les tarifs actifs
    de toutes les formations. Permet au site statique d'afficher les prix à jour."""
    formations = session.query(Formation).filter_by(actif=True).all()
    result = []
    for f in formations:
        tarifs_actifs = [t for t in f.tarifs if t.actif]
        for t in tarifs_actifs:
            result.append({
                "formation": f.titre,
                "nom_option": t.nom_option,
                "prix": float(t.prix_final()),
                "prix_barre": float(t.prix) if t.prix_final() < float(t.prix) else None,
            })
    return result


@router.get("/api/heartbeat")
def heartbeat(session: Session = Depends(obtenir_session)):
    """Réveille Neon immédiatement — appelé par le frontend sur chaque page."""
    session.execute(text("SELECT 1"))
    return {"ok": True}
