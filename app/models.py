"""
Modèle de données de la plateforme LMS -- version serveur, à jour avec toutes
les décisions validées au fil des sessions de maquette (admin + élève).
"""
import secrets
from datetime import datetime
import bcrypt
from sqlalchemy import (
    create_engine, Column, Integer, String, Boolean, DateTime, ForeignKey,
    UniqueConstraint, Text
)
from sqlalchemy.orm import declarative_base, relationship, Session

Base = declarative_base()


def hacher_mot_de_passe(mot_de_passe_clair: str) -> str:
    sel = bcrypt.gensalt()
    return bcrypt.hashpw(mot_de_passe_clair.encode("utf-8"), sel).decode("utf-8")


def verifier_mot_de_passe(mot_de_passe_clair: str, hash_stocke: str) -> bool:
    if not hash_stocke:
        return False
    try:
        return bcrypt.checkpw(mot_de_passe_clair.encode("utf-8"), hash_stocke.encode("utf-8"))
    except ValueError:
        return False


def generer_token_reinitialisation() -> str:
    return secrets.token_urlsafe(32)


class Formation(Base):
    __tablename__ = "formations"

    id = Column(Integer, primary_key=True)
    titre = Column(String(200), nullable=False)
    couleur = Column(String(20))
    presentation_html = Column(Text)
    nb_niveaux = Column(Integer, nullable=False, default=3)
    actif = Column(Boolean, default=True)
    fichier_recu_nom = Column(String(300))
    cree_le = Column(DateTime, default=datetime.utcnow)

    modules = relationship("Module", back_populates="formation", order_by="Module.ordre",
                            cascade="all, delete-orphan")
    acces_eleves = relationship("AccesFormation", back_populates="formation")
    jours_par_niveau = relationship("JoursAccompagnementNiveau", back_populates="formation",
                                     cascade="all, delete-orphan")

    def jours_pour_niveau(self, niveau: int) -> int:
        for j in self.jours_par_niveau:
            if j.niveau == niveau:
                return j.jours
        return 0


class JoursAccompagnementNiveau(Base):
    __tablename__ = "jours_accompagnement_niveau"
    __table_args__ = (UniqueConstraint("formation_id", "niveau", name="uniq_formation_niveau"),)

    id = Column(Integer, primary_key=True)
    formation_id = Column(Integer, ForeignKey("formations.id"), nullable=False)
    niveau = Column(Integer, nullable=False)
    jours = Column(Integer, nullable=False, default=0)

    formation = relationship("Formation", back_populates="jours_par_niveau")


class Module(Base):
    __tablename__ = "modules"

    id = Column(Integer, primary_key=True)
    formation_id = Column(Integer, ForeignKey("formations.id"), nullable=False)
    titre = Column(String(200), nullable=False)
    presentation_html = Column(Text)
    niveau_requis = Column(Integer, nullable=False, default=1)
    ordre = Column(Integer, nullable=False)
    fichier_recu_nom = Column(String(300))

    formation = relationship("Formation", back_populates="modules")
    chapitres = relationship("Chapitre", back_populates="module", order_by="Chapitre.ordre",
                              cascade="all, delete-orphan")


class Chapitre(Base):
    __tablename__ = "chapitres"

    id = Column(Integer, primary_key=True)
    module_id = Column(Integer, ForeignKey("modules.id"), nullable=False)
    titre = Column(String(200), nullable=False)
    contenu_html = Column(Text)
    ordre = Column(Integer, nullable=False)
    niveau_requis = Column(Integer, nullable=False, default=1)
    fichier_recu_nom = Column(String(300))

    module = relationship("Module", back_populates="chapitres")
    medias = relationship("Media", back_populates="chapitre", cascade="all, delete-orphan")
    validations = relationship("ValidationChapitre", back_populates="chapitre")


class Media(Base):
    __tablename__ = "medias"

    id = Column(Integer, primary_key=True)
    chapitre_id = Column(Integer, ForeignKey("chapitres.id"), nullable=False)
    type = Column(String(20), nullable=False)
    titre = Column(String(200))
    url = Column(Text, nullable=False)
    telechargeable = Column(Boolean, default=False)

    chapitre = relationship("Chapitre", back_populates="medias")


class Eleve(Base):
    __tablename__ = "eleves"

    id = Column(Integer, primary_key=True)
    nom = Column(String(100), nullable=False)
    prenom = Column(String(100), nullable=False)
    email = Column(String(200), nullable=False, unique=True)
    mot_de_passe_hash = Column(String(255))
    actif = Column(Boolean, default=True)
    cree_le = Column(DateTime, default=datetime.utcnow)
    # Statistiques de connexion (colonnes ajoutées via migration Neon)
    nb_connexions = Column(Integer, default=0)
    derniere_connexion = Column(DateTime, nullable=True)

    acces_formations = relationship("AccesFormation", back_populates="eleve",
                                     cascade="all, delete-orphan")
    validations = relationship("ValidationChapitre", back_populates="eleve")
    tokens = relationship("TokenAuthEleve", back_populates="eleve", cascade="all, delete-orphan")

    def definir_mot_de_passe(self, mot_de_passe_clair: str) -> None:
        self.mot_de_passe_hash = hacher_mot_de_passe(mot_de_passe_clair)

    def verifier_mot_de_passe(self, mot_de_passe_clair: str) -> bool:
        return verifier_mot_de_passe(mot_de_passe_clair, self.mot_de_passe_hash)


class TokenAuthEleve(Base):
    __tablename__ = "tokens_auth_eleves"

    id = Column(Integer, primary_key=True)
    eleve_id = Column(Integer, ForeignKey("eleves.id"), nullable=False)
    token = Column(String(100), nullable=False, unique=True)
    type_token = Column(String(30), nullable=False)
    cree_le = Column(DateTime, default=datetime.utcnow)
    expire_le = Column(DateTime, nullable=False)
    utilise_le = Column(DateTime, nullable=True)

    eleve = relationship("Eleve", back_populates="tokens")

    def est_valide(self) -> bool:
        return self.utilise_le is None and datetime.utcnow() < self.expire_le


class Administrateur(Base):
    __tablename__ = "administrateurs"

    id = Column(Integer, primary_key=True)
    nom = Column(String(100), nullable=False)
    prenom = Column(String(100), nullable=False)
    email = Column(String(200), nullable=False, unique=True)
    telephone = Column(String(50))
    mot_de_passe_hash = Column(String(255))
    photo_url = Column(Text)
    logo_url = Column(Text)
    lien_github = Column(String(500))
    lien_render = Column(String(500))
    lien_neon = Column(String(500))
    cree_le = Column(DateTime, default=datetime.utcnow)

    tokens = relationship("TokenAuthAdmin", back_populates="administrateur", cascade="all, delete-orphan")

    def definir_mot_de_passe(self, mot_de_passe_clair: str) -> None:
        self.mot_de_passe_hash = hacher_mot_de_passe(mot_de_passe_clair)

    def verifier_mot_de_passe(self, mot_de_passe_clair: str) -> bool:
        return verifier_mot_de_passe(mot_de_passe_clair, self.mot_de_passe_hash)


class TokenAuthAdmin(Base):
    __tablename__ = "tokens_auth_admin"

    id = Column(Integer, primary_key=True)
    administrateur_id = Column(Integer, ForeignKey("administrateurs.id"), nullable=False)
    token = Column(String(100), nullable=False, unique=True)
    type_token = Column(String(30), nullable=False)
    cree_le = Column(DateTime, default=datetime.utcnow)
    expire_le = Column(DateTime, nullable=False)
    utilise_le = Column(DateTime, nullable=True)

    administrateur = relationship("Administrateur", back_populates="tokens")

    def est_valide(self) -> bool:
        return self.utilise_le is None and datetime.utcnow() < self.expire_le


class AccesFormation(Base):
    __tablename__ = "acces_formations"
    __table_args__ = (UniqueConstraint("eleve_id", "formation_id", name="uniq_eleve_formation"),)

    id = Column(Integer, primary_key=True)
    eleve_id = Column(Integer, ForeignKey("eleves.id"), nullable=False)
    formation_id = Column(Integer, ForeignKey("formations.id"), nullable=False)
    niveau = Column(Integer, nullable=False, default=1)
    diplome_envoye = Column(Boolean, default=False)
    accorde_le = Column(DateTime, default=datetime.utcnow)

    eleve = relationship("Eleve", back_populates="acces_formations")
    formation = relationship("Formation", back_populates="acces_eleves")
    seances_accompagnement = relationship("SeanceAccompagnement", back_populates="acces",
                                           cascade="all, delete-orphan")

    def jours_accompagnement_restants(self) -> int:
        total = self.formation.jours_pour_niveau(self.niveau)
        utilises = len(self.seances_accompagnement)
        return max(0, total - utilises)


class SeanceAccompagnement(Base):
    __tablename__ = "seances_accompagnement"

    id = Column(Integer, primary_key=True)
    acces_id = Column(Integer, ForeignKey("acces_formations.id"), nullable=False)
    date_seance = Column(DateTime, default=datetime.utcnow)

    acces = relationship("AccesFormation", back_populates="seances_accompagnement")


class ValidationChapitre(Base):
    __tablename__ = "validations_chapitres"
    __table_args__ = (UniqueConstraint("eleve_id", "chapitre_id", name="uniq_eleve_chapitre"),)

    id = Column(Integer, primary_key=True)
    eleve_id = Column(Integer, ForeignKey("eleves.id"), nullable=False)
    chapitre_id = Column(Integer, ForeignKey("chapitres.id"), nullable=False)
    valide_le = Column(DateTime, default=datetime.utcnow)

    eleve = relationship("Eleve", back_populates="validations")
    chapitre = relationship("Chapitre", back_populates="validations")


def sequence_chapitres(formation: Formation) -> list:
    chapitres = []
    for module in formation.modules:
        chapitres.extend(module.chapitres)
    return sorted(chapitres, key=lambda c: c.ordre)


def chapitre_dans_le_niveau(formation: Formation, niveau_eleve: int, chapitre) -> bool:
    if formation.nb_niveaux <= 1:
        return True
    if niveau_eleve < chapitre.module.niveau_requis:
        return False
    if niveau_eleve < chapitre.niveau_requis:
        return False
    return True


def chapitre_est_accessible(session: Session, eleve_id: int, chapitre) -> tuple:
    formation = chapitre.module.formation
    acces = (
        session.query(AccesFormation)
        .filter_by(eleve_id=eleve_id, formation_id=formation.id)
        .first()
    )
    if acces is None:
        return False, "aucun_acces"
    if formation.nb_niveaux > 1 and acces.niveau < chapitre.module.niveau_requis:
        return False, "niveau_module_insuffisant"
    if formation.nb_niveaux > 1 and acces.niveau < chapitre.niveau_requis:
        return False, "niveau_chapitre_insuffisant"
    seq = sequence_chapitres(formation)
    idx = next(i for i, c in enumerate(seq) if c.id == chapitre.id)
    for i in range(idx - 1, -1, -1):
        precedent = seq[i]
        if not chapitre_dans_le_niveau(formation, acces.niveau, precedent):
            continue
        deja_valide = (
            session.query(ValidationChapitre)
            .filter_by(eleve_id=eleve_id, chapitre_id=precedent.id)
            .first()
        )
        if deja_valide is None:
            return False, "chapitre_precedent_non_valide"
        break
    return True, ""


def progression_pourcentage(session: Session, eleve_id: int, formation: Formation) -> float:
    acces = (
        session.query(AccesFormation)
        .filter_by(eleve_id=eleve_id, formation_id=formation.id)
        .first()
    )
    if acces is None:
        return 0.0
    seq_visible = [c for c in sequence_chapitres(formation)
                   if chapitre_dans_le_niveau(formation, acces.niveau, c)]
    if not seq_visible:
        return 0.0
    ids_visibles = [c.id for c in seq_visible]
    valides = (
        session.query(ValidationChapitre)
        .filter(ValidationChapitre.eleve_id == eleve_id, ValidationChapitre.chapitre_id.in_(ids_visibles))
        .count()
    )
    return round(100 * valides / len(seq_visible), 1)


def module_est_termine(session: Session, eleve_id: int, module: Module) -> bool:
    chapitre_ids = [c.id for c in module.chapitres]
    if not chapitre_ids:
        return False
    nb_valides = (
        session.query(ValidationChapitre)
        .filter(ValidationChapitre.eleve_id == eleve_id, ValidationChapitre.chapitre_id.in_(chapitre_ids))
        .count()
    )
    return nb_valides == len(chapitre_ids)


def formation_est_terminee(session: Session, eleve_id: int, formation: Formation) -> bool:
    if not formation.modules:
        return False
    return all(module_est_termine(session, eleve_id, m) for m in formation.modules)


def dupliquer_chapitre(session: Session, chapitre_id: int) -> Chapitre:
    original = session.get(Chapitre, chapitre_id)
    session.query(Chapitre).filter(Chapitre.ordre > original.ordre).update(
        {Chapitre.ordre: Chapitre.ordre + 1}
    )
    copie = Chapitre(
        module_id=original.module_id,
        titre=original.titre + " (copie)",
        contenu_html=original.contenu_html,
        ordre=original.ordre + 1,
        niveau_requis=original.niveau_requis,
    )
    session.add(copie)
    session.flush()
    for media in original.medias:
        session.add(Media(
            chapitre_id=copie.id, type=media.type, titre=media.titre,
            url=media.url, telechargeable=media.telechargeable,
        ))
    session.commit()
    return copie


def deplacer_chapitre_vers_module(session: Session, chapitre_id: int, nouveau_module_id: int) -> None:
    chapitre = session.get(Chapitre, chapitre_id)
    nouveau_module = session.get(Module, nouveau_module_id)
    if nouveau_module.formation_id != chapitre.module.formation_id:
        raise ValueError("Impossible de déplacer un chapitre vers une autre formation")
    dernier_ordre = (
        session.query(Chapitre)
        .join(Module)
        .filter(Module.formation_id == nouveau_module.formation_id)
        .order_by(Chapitre.ordre.desc())
        .first()
    )
    chapitre.module_id = nouveau_module_id
    chapitre.ordre = (dernier_ordre.ordre + 1) if dernier_ordre else 1
    session.commit()


def valider_chapitre(session: Session, eleve_id: int, chapitre_id: int) -> None:
    existe = (
        session.query(ValidationChapitre)
        .filter_by(eleve_id=eleve_id, chapitre_id=chapitre_id)
        .first()
    )
    if existe is None:
        session.add(ValidationChapitre(eleve_id=eleve_id, chapitre_id=chapitre_id))
        session.commit()


def dupliquer_formation(session: Session, formation_id: int) -> Formation:
    original = session.get(Formation, formation_id)
    copie = Formation(
        titre=original.titre + " (copie)",
        couleur=original.couleur,
        presentation_html=original.presentation_html,
        nb_niveaux=original.nb_niveaux,
        actif=False,
    )
    session.add(copie)
    session.flush()
    for jpn in original.jours_par_niveau:
        session.add(JoursAccompagnementNiveau(formation_id=copie.id, niveau=jpn.niveau, jours=jpn.jours))
    for module in original.modules:
        module_copie = Module(
            formation_id=copie.id, titre=module.titre,
            presentation_html=module.presentation_html,
            niveau_requis=module.niveau_requis, ordre=module.ordre,
        )
        session.add(module_copie)
        session.flush()
        for chapitre in module.chapitres:
            chapitre_copie = Chapitre(
                module_id=module_copie.id, titre=chapitre.titre,
                contenu_html=chapitre.contenu_html, ordre=chapitre.ordre,
                niveau_requis=chapitre.niveau_requis,
            )
            session.add(chapitre_copie)
            session.flush()
            for media in chapitre.medias:
                session.add(Media(
                    chapitre_id=chapitre_copie.id, type=media.type, titre=media.titre,
                    url=media.url, telechargeable=media.telechargeable,
                ))
    session.commit()
    return copie


if __name__ == "__main__":
    engine = create_engine("sqlite:///lms_prototype.db", echo=False)
    Base.metadata.create_all(engine)
    print("Structure de données créée avec succès dans lms_prototype.db")

class CercleFemmes(Base):
    """Bloc unique ('singleton') pour annoncer le prochain Cercle de Femmes
    sur le site vitrine. Laurence le modifie depuis l'admin ; le site public
    va chercher ces infos via une route publique en lecture seule."""
    __tablename__ = "cercle_femmes"

    id = Column(Integer, primary_key=True)
    titre = Column(String(200), default="Cercle de Femmes")
    date_evenement = Column(String(150))   # texte libre, ex: "Samedi 12 septembre 2026, 14h-17h"
    lieu = Column(String(300))             # ex: "Cabinet de Véranne (42520)"
    description_html = Column(Text)        # thème, déroulé, informations pratiques
    photo_url = Column(Text)               # optionnel, image encodée en base64
    publie = Column(Boolean, default=True) # si False, le site affiche un message d'attente
    mis_a_jour_le = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


def obtenir_ou_creer_cercle_femmes(session: Session) -> "CercleFemmes":
    """Il n'existe qu'une seule fiche 'prochain cercle' à la fois -- on la
    récupère si elle existe, sinon on la crée avec des valeurs de départ
    réalistes (Laurence les modifiera ensuite depuis l'admin)."""
    cercle = session.query(CercleFemmes).first()
    if cercle is None:
        cercle = CercleFemmes(
            titre="Cercle de Femmes de rentrée",
            date_evenement="Mercredi 10 septembre 2026, 14h-17h",
            lieu="Cabinet de Véranne (42520)",
            description_html="Un cercle pour se retrouver après l'été, se relier à son cycle et à la puissance du féminin sacré. Places limitées, inscription par message.",
            photo_url="images/laurence-huiles-cadran.jpg",
            publie=True,
        )
        session.add(cercle)
        session.commit()
        session.refresh(cercle)
    return cercle
