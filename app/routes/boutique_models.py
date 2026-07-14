"""
Modèles de données pour la boutique (catalogue, tarifs, promotions,
codes promo, commandes).

Principe : chaque Formation peut avoir 1 ou plusieurs "TarifFormation" --
1 seul pour une formation classique, plusieurs pour une formation à options
indépendantes et non cumulables, ou plusieurs paliers cumulables (niveau
1/2/3) avec possibilité de payer la différence pour monter de niveau.
"""
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, ForeignKey, Text, Numeric, Table
)
from sqlalchemy.orm import relationship, Session

from ..models import Base, Formation, Eleve, AccesFormation


codes_promo_tarifs = Table(
    "codes_promo_tarifs",
    Base.metadata,
    Column("code_promo_id", Integer, ForeignKey("codes_promo.id"), primary_key=True),
    Column("tarif_formation_id", Integer, ForeignKey("tarifs_formation.id"), primary_key=True),
)


class TarifFormation(Base):
    __tablename__ = "tarifs_formation"

    id = Column(Integer, primary_key=True)
    formation_id = Column(Integer, ForeignKey("formations.id"), nullable=False)
    niveau = Column(Integer, nullable=False, default=1)
    nom_option = Column(String(150), default="Tarif unique")
    prix = Column(Numeric(10, 2), nullable=False)
    promo_active = Column(Boolean, default=False)
    promo_pourcentage = Column(Integer, nullable=True)
    autoriser_3x = Column(Boolean, default=False)
    cumulable = Column(Boolean, default=False)  # True = palier d'une même formation (montée de niveau possible)
    ordre = Column(Integer, default=1)
    actif = Column(Boolean, default=True)

    formation = relationship("Formation", backref="tarifs")
    lignes_commande = relationship("LigneCommande", back_populates="tarif")

    def prix_final(self) -> float:
        prix = float(self.prix)
        if self.promo_active and self.promo_pourcentage:
            return round(prix * (1 - self.promo_pourcentage / 100), 2)
        return prix


class CodePromo(Base):
    __tablename__ = "codes_promo"

    id = Column(Integer, primary_key=True)
    code = Column(String(50), nullable=False, unique=True)
    type_reduction = Column(String(20), nullable=False)
    valeur = Column(Numeric(10, 2), nullable=False)
    actif = Column(Boolean, default=True)
    reserve_premier_achat = Column(Boolean, default=False)
    date_fin = Column(DateTime, nullable=True)
    cree_le = Column(DateTime, default=datetime.utcnow)

    tarifs_concernes = relationship("TarifFormation", secondary=codes_promo_tarifs, backref="codes_promo")

    def est_valide_maintenant(self) -> bool:
        if not self.actif:
            return False
        if self.date_fin and datetime.utcnow() > self.date_fin:
            return False
        return True


class Commande(Base):
    __tablename__ = "commandes"

    id = Column(Integer, primary_key=True)
    eleve_id = Column(Integer, ForeignKey("eleves.id"), nullable=False)
    montant_total = Column(Numeric(10, 2), nullable=False)
    moyen_paiement = Column(String(30), nullable=True)
    stripe_session_id = Column(String(200), nullable=True, unique=True)
    statut = Column(String(20), default="en_attente")
    code_promo_utilise = Column(String(50), nullable=True)
    cree_le = Column(DateTime, default=datetime.utcnow)
    payee_le = Column(DateTime, nullable=True)

    eleve = relationship("Eleve", backref="commandes")
    lignes = relationship("LigneCommande", back_populates="commande", cascade="all, delete-orphan")


class LigneCommande(Base):
    __tablename__ = "lignes_commande"

    id = Column(Integer, primary_key=True)
    commande_id = Column(Integer, ForeignKey("commandes.id"), nullable=False)
    tarif_formation_id = Column(Integer, ForeignKey("tarifs_formation.id"), nullable=False)
    prix_paye = Column(Numeric(10, 2), nullable=False)  # montant RÉEL payé -- sert de base au calcul de montée en niveau

    commande = relationship("Commande", back_populates="lignes")
    tarif = relationship("TarifFormation", back_populates="lignes_commande")


# --- Fonctions utilitaires -------------------------------------------------

def a_deja_achete(session: Session, eleve_id: int) -> bool:
    return (
        session.query(Commande)
        .filter(Commande.eleve_id == eleve_id, Commande.statut == "payee")
        .first()
        is not None
    )


def calculer_meilleur_prix(tarif: TarifFormation, code):
    prix_original = float(tarif.prix)
    prix_promo = tarif.prix_final()
    meilleur_prix = prix_promo
    source = "promo" if prix_promo < prix_original else None

    if code and tarif in code.tarifs_concernes:
        if code.type_reduction == "pourcentage":
            prix_code = round(prix_original * (1 - float(code.valeur) / 100), 2)
        else:
            prix_code = max(0.0, prix_original - float(code.valeur))
        if prix_code < meilleur_prix:
            meilleur_prix = prix_code
            source = "code"

    return meilleur_prix, source


def calculer_panier(session: Session, tarif_ids, code_str, eleve_id: int) -> dict:
    """Calcule le détail complet d'un panier standard (nouvel achat).
    Fait foi à la fois pour l'aperçu affiché et pour la création du paiement."""
    tarifs = (
        session.query(TarifFormation)
        .filter(TarifFormation.id.in_(tarif_ids), TarifFormation.actif == True)  # noqa: E712
        .all()
    )

    code = None
    erreur_code = None
    if code_str:
        code = session.query(CodePromo).filter_by(code=code_str.strip().upper()).first()
        if code is None or not code.est_valide_maintenant():
            erreur_code = "Ce code n'existe pas ou n'est plus actif."
            code = None
        elif code.reserve_premier_achat and a_deja_achete(session, eleve_id):
            erreur_code = "Ce code est réservé au premier achat -- tu l'as déjà utilisé."
            code = None

    lignes = []
    total = 0.0
    for tarif in tarifs:
        prix, source = calculer_meilleur_prix(tarif, code)
        total += prix
        lignes.append({
            "tarif_id": tarif.id,
            "nom": f"{tarif.formation.titre} — {tarif.nom_option}" if tarif.nom_option != "Tarif unique" else tarif.formation.titre,
            "prix_original": float(tarif.prix),
            "prix_final": prix,
            "reduction_appliquee": source,
            "autoriser_3x": tarif.autoriser_3x,
            "type": "achat",
        })

    return {
        "lignes": lignes,
        "total": round(total, 2),
        "code_applique": code.code if code else None,
        "erreur_code": erreur_code,
        "trois_x_disponible": all(l["autoriser_3x"] for l in lignes) if lignes else False,
    }


def propositions_montee_niveau(session: Session, eleve_id: int) -> list:
    """Pour chaque formation à paliers cumulables déjà partiellement possédée
    par l'élève, calcule le prix de la montée vers le(s) niveau(x)
    supérieur(s) -- prix du nouveau palier moins ce qui a RÉELLEMENT été payé
    pour le palier actuel (pas le prix catalogue)."""
    propositions = []
    acces_liste = (
        session.query(AccesFormation).filter_by(eleve_id=eleve_id).all()
    )
    for acces in acces_liste:
        formation = acces.formation
        tarifs_formation = (
            session.query(TarifFormation)
            .filter_by(formation_id=formation.id, cumulable=True, actif=True)
            .order_by(TarifFormation.niveau)
            .all()
        )
        if not tarifs_formation:
            continue  # formation sans paliers cumulables -- rien à proposer

        tarifs_superieurs = [t for t in tarifs_formation if t.niveau > acces.niveau]
        if not tarifs_superieurs:
            continue  # déjà au niveau maximum

        # Montant réellement payé pour le niveau actuel : dernière ligne de
        # commande payée correspondant à ce tarif exact (le plus fiable),
        # sinon on retombe sur le prix catalogue actuel comme filet de sécurité.
        tarif_actuel = next((t for t in tarifs_formation if t.niveau == acces.niveau), None)
        montant_paye_actuel = None
        if tarif_actuel:
            ligne = (
                session.query(LigneCommande)
                .join(Commande)
                .filter(
                    Commande.eleve_id == eleve_id,
                    Commande.statut == "payee",
                    LigneCommande.tarif_formation_id == tarif_actuel.id,
                )
                .order_by(Commande.payee_le.desc())
                .first()
            )
            if ligne:
                montant_paye_actuel = float(ligne.prix_paye)
        if montant_paye_actuel is None and tarif_actuel:
            montant_paye_actuel = tarif_actuel.prix_final()

        for tarif_sup in tarifs_superieurs:
            prix_sup = tarif_sup.prix_final()
            difference = round(max(0.0, prix_sup - (montant_paye_actuel or 0)), 2)
            propositions.append({
                "formation_id": formation.id,
                "formation_titre": formation.titre,
                "niveau_actuel": acces.niveau,
                "niveau_propose": tarif_sup.niveau,
                "nom_option": tarif_sup.nom_option,
                "tarif_id": tarif_sup.id,
                "difference_a_payer": difference,
            })

    return propositions
