"""
Modèle de données de la plateforme LMS -- version serveur, à jour avec toutes
les décisions validées au fil des sessions de maquette (admin + élève).
"""
import secrets
from datetime import datetime
import bcrypt
from sqlalchemy import (
    create_engine, Column, Integer, String, Boolean, DateTime, ForeignKey, Numeric,
    UniqueConstraint, Text
)
from sqlalchemy.orm import declarative_base, relationship, Session, deferred, column_property
from sqlalchemy import func

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
    # CORRECTION TRANSFERT NEON (18/10/2026) : presentation_html et image_url peuvent peser
    # plusieurs Mo (images base64). Sans deferred, /api/tarifs-site (appelée à chaque page
    # du site vitrine) relisait ~4 Mo dans Neon à chaque visite. Chargés seulement si utilisés.
    presentation_html = deferred(Column(Text))
    nb_niveaux = Column(Integer, nullable=False, default=3)
    ordre_affichage = Column(Integer, nullable=False, default=0)
    actif = Column(Boolean, default=True)
    fichier_recu_nom = Column(String(300))
    cree_le = Column(DateTime, default=datetime.utcnow)
    image_url = deferred(Column(Text, nullable=True))
    description_courte = Column(Text, nullable=True)
    lien_visio = Column(String(500), nullable=True)
    acces_auto = Column(Boolean, default=False, nullable=False)

    modules = relationship("Module", back_populates="formation", order_by="Module.ordre",
                           cascade="all, delete-orphan")
    medias = relationship("MediaFormation", back_populates="formation", cascade="all, delete-orphan")
    acces_eleves = relationship("AccesFormation", back_populates="formation")
    jours_par_niveau = relationship("JoursAccompagnementNiveau", back_populates="formation",
                                   cascade="all, delete-orphan")

    def jours_pour_niveau(self, niveau: int) -> int:
        for j in self.jours_par_niveau:
            if j.niveau == niveau:
                return j.jours
        return 0

    def jours_visio_pour_niveau(self, niveau: int) -> int:
        for j in self.jours_par_niveau:
            if j.niveau == niveau:
                return j.jours_visio
        return 0

class JoursAccompagnementNiveau(Base):
    __tablename__ = "jours_accompagnement_niveau"
    __table_args__ = (UniqueConstraint("formation_id", "niveau", name="uniq_formation_niveau"),)

    id = Column(Integer, primary_key=True)
    formation_id = Column(Integer, ForeignKey("formations.id"), nullable=False)
    niveau = Column(Integer, nullable=False)
    jours = Column(Integer, nullable=False, default=0)
    jours_visio = Column(Integer, nullable=False, default=0)

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
    medias = relationship("MediaModule", back_populates="module", cascade="all, delete-orphan")

class Chapitre(Base):
    __tablename__ = "chapitres"

    id = Column(Integer, primary_key=True)
    module_id = Column(Integer, ForeignKey("modules.id"), nullable=False)
    titre = Column(String(200), nullable=False)
    # CORRECTION TRANSFERT NEON : contenu_html peut contenir des Mo d'images base64.
    # deferred=True évite de le charger lors des requêtes en masse (ex : validation
    # de chapitre avec selectinload sur toute la formation). Il n'est chargé que
    # lorsque explicitement accédé (route detail_chapitre, édition admin).
    contenu_html = deferred(Column(Text))
    ordre = Column(Integer, nullable=False)
    niveau_requis = Column(Integer, nullable=False, default=1)
    fichier_recu_nom = Column(String(300))
    # Lien Resalib optionnel -- renseigné par l'admin au niveau du chapitre.
    # Si présent, un email avec ce lien est envoyé automatiquement à l'élève
    # quand il valide ce chapitre (première séance de coaching).
    lien_coaching = Column(String(500), nullable=True)

    module = relationship("Module", back_populates="chapitres")
    medias = relationship("Media", back_populates="chapitre", cascade="all, delete-orphan")
    # cascade : sans elle, supprimer un chapitre déjà validé par une élève (ou un compte
    # test « tout valider ») échouait (chapitre_id mis à NULL alors qu'il est obligatoire).
    validations = relationship("ValidationChapitre", back_populates="chapitre", cascade="all, delete-orphan")
    reponses_chapitres = relationship("ReponseChapitre", back_populates="chapitre", cascade="all, delete-orphan", passive_deletes=True)

class Media(Base):
    __tablename__ = "medias"

    id = Column(Integer, primary_key=True)
    chapitre_id = Column(Integer, ForeignKey("chapitres.id"), nullable=False)
    type = Column(String(20), nullable=False)
    titre = Column(String(200))
    # url peut contenir un fichier entier encodé en base64 (audio de 30 Mo -> ~40 Mo de texte).
    # deferred : jamais chargé dans les listes ; le fichier est servi à la demande par
    # app/routes/medias_fichiers.py. est_integre permet de savoir si c'est un fichier
    # (data:...) ou un lien externe sans charger la colonne entière.
    url = deferred(Column(Text, nullable=False))
    est_integre = column_property(func.substr(url, 1, 5) == "data:")
    # fichier stocké sur Cloudflare R2 (url "r2:<clé>", voir app/stockage_r2.py) -- pas une colonne, aucune migration
    est_r2 = column_property(func.substr(url, 1, 3) == "r2:")
    # taille du texte base64 (octet_length lit la taille sans décompresser le fichier en Postgres)
    taille_texte = column_property(func.octet_length(url))
    telechargeable = Column(Boolean, default=False)

    chapitre = relationship("Chapitre", back_populates="medias")

class MediaModule(Base):
    """Media attache a un module (PDF, audio, lien externe).
    Table separee de medias pour ne pas toucher aux donnees existantes."""
    __tablename__ = "medias_module"

    id = Column(Integer, primary_key=True)
    module_id = Column(Integer, ForeignKey("modules.id"), nullable=False)
    type = Column(String(20), nullable=False)
    titre = Column(String(200))
    # url peut contenir un fichier entier encodé en base64 (audio de 30 Mo -> ~40 Mo de texte).
    # deferred : jamais chargé dans les listes ; le fichier est servi à la demande par
    # app/routes/medias_fichiers.py. est_integre permet de savoir si c'est un fichier
    # (data:...) ou un lien externe sans charger la colonne entière.
    url = deferred(Column(Text, nullable=False))
    est_integre = column_property(func.substr(url, 1, 5) == "data:")
    # fichier stocké sur Cloudflare R2 (url "r2:<clé>", voir app/stockage_r2.py) -- pas une colonne, aucune migration
    est_r2 = column_property(func.substr(url, 1, 3) == "r2:")
    # taille du texte base64 (octet_length lit la taille sans décompresser le fichier en Postgres)
    taille_texte = column_property(func.octet_length(url))
    telechargeable = Column(Boolean, default=False)

    module = relationship("Module", back_populates="medias")


class MediaFormation(Base):
    """Media attache a une formation (PDF, audio, lien externe).
    Table separee de medias pour ne pas toucher aux donnees existantes."""
    __tablename__ = "medias_formation"

    id = Column(Integer, primary_key=True)
    formation_id = Column(Integer, ForeignKey("formations.id"), nullable=False)
    type = Column(String(20), nullable=False)
    titre = Column(String(200))
    # url peut contenir un fichier entier encodé en base64 (audio de 30 Mo -> ~40 Mo de texte).
    # deferred : jamais chargé dans les listes ; le fichier est servi à la demande par
    # app/routes/medias_fichiers.py. est_integre permet de savoir si c'est un fichier
    # (data:...) ou un lien externe sans charger la colonne entière.
    url = deferred(Column(Text, nullable=False))
    est_integre = column_property(func.substr(url, 1, 5) == "data:")
    # fichier stocké sur Cloudflare R2 (url "r2:<clé>", voir app/stockage_r2.py) -- pas une colonne, aucune migration
    est_r2 = column_property(func.substr(url, 1, 3) == "r2:")
    # taille du texte base64 (octet_length lit la taille sans décompresser le fichier en Postgres)
    taille_texte = column_property(func.octet_length(url))
    telechargeable = Column(Boolean, default=False)

    formation = relationship("Formation", back_populates="medias")


class SauvegardeMediaBase64(Base):
    """Copie de sécurité d'un média déplacé de Neon vers Cloudflare R2 (19/10/2026).
    Nouvelle table (create_all). Permet de revenir en arrière ; à vider une fois
    la lecture depuis R2 testée (POST /admin/stockage-r2/purger-sauvegardes)."""
    __tablename__ = "sauvegardes_medias_base64"

    id = Column(Integer, primary_key=True)
    nature = Column(String(20), nullable=False)      # chapitre | module | formation
    media_id = Column(Integer, nullable=False)
    ancienne_url = deferred(Column(Text, nullable=False))
    nouvelle_url = Column(Text, nullable=False)       # r2:<clé>
    migre_le = Column(DateTime, default=datetime.utcnow)


class Eleve(Base):
    __tablename__ = "eleves"

    id = Column(Integer, primary_key=True)
    nom = Column(String(100), nullable=False)
    prenom = Column(String(100), nullable=False)
    email = Column(String(200), nullable=False, unique=True)
    mot_de_passe_hash = Column(String(255))
    actif = Column(Boolean, default=True)
    compte_test = Column(Boolean, default=False)
    cree_le = Column(DateTime, default=datetime.utcnow)
    # Statistiques de connexion (colonnes ajoutées via migration Neon)
    nb_connexions = Column(Integer, default=0)
    derniere_connexion = Column(DateTime, nullable=True)
    lien_resalib = Column(String(500), nullable=True)  # lien Resalib de l'élève
    lien_resalib_visio = Column(String(500), nullable=True)  # lien Resalib visio

    acces_formations = relationship("AccesFormation", back_populates="eleve",
                                   cascade="all, delete-orphan")
    validations = relationship("ValidationChapitre", back_populates="eleve")
    reponses_chapitres = relationship("ReponseChapitre", back_populates="eleve", cascade="all, delete-orphan", passive_deletes=True)
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
    # CORRECTION TRANSFERT NEON : photo_url et logo_url sont des images base64
    # potentiellement lourdes. deferred=True évite de les charger dans les requêtes
    # d'authentification et autres requêtes qui n'ont pas besoin des images.
    photo_url = deferred(Column(Text))
    logo_url = deferred(Column(Text))
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

    def jours_cabinet_utilises(self) -> int:
        return sum(1 for s in self.seances_accompagnement if s.statut == "realise" and s.type_accompagnement == "cabinet")

    def jours_visio_utilises(self) -> int:
        return sum(1 for s in self.seances_accompagnement if s.statut == "realise" and s.type_accompagnement == "visio")

    def jours_cabinet_restants(self) -> int:
        total = self.formation.jours_pour_niveau(self.niveau)
        return max(0, total - self.jours_cabinet_utilises())

    def jours_visio_restants(self) -> int:
        total = self.formation.jours_visio_pour_niveau(self.niveau)
        return max(0, total - self.jours_visio_utilises())

    def jours_accompagnement_restants(self) -> int:
        """Compatibilité ascendante — retourne les jours cabinet restants."""
        return self.jours_cabinet_restants()

class SeanceAccompagnement(Base):
    __tablename__ = "seances_accompagnement"

    id = Column(Integer, primary_key=True)
    acces_id = Column(Integer, ForeignKey("acces_formations.id"), nullable=False)
    date_seance = Column(DateTime, default=datetime.utcnow)

    # Colonnes ajoutées pour le suivi des coachings
    lien_resalib = Column(String(500), nullable=True)   # lien envoyé à la cliente
    type_envoi = Column(String(20), nullable=True)      # "auto" ou "manuel"
    statut = Column(String(20), nullable=False, default="en_attente")  # "en_attente" | "realise"
    date_realise = Column(DateTime, nullable=True)      # renseigné par l'admin quand la séance a eu lieu

    type_accompagnement = Column(String(20), nullable=False, default="cabinet")  # "cabinet" | "visio"
    # Lien optionnel vers la réservation native (agenda intégré)
    reservation_id = Column(Integer, ForeignKey("agenda_reservations.id"), nullable=True)

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

class ReponseChapitre(Base):
    """Réponses d'une élève au questionnaire d'un chapitre (cases ☐ et lignes de
    pointillés du Word, rendues interactives sur la page élève).
    reponses : JSON, liste d'éléments
      {"type": "case", "libelle": "...", "coche": true}
      {"type": "texte", "question": "...", "valeur": "..."}
    Table créée automatiquement par create_all (nouvelle table, pas de colonne
    ajoutée à une table existante)."""
    __tablename__ = "reponses_chapitres"
    __table_args__ = (UniqueConstraint("eleve_id", "chapitre_id", name="uniq_reponse_eleve_chapitre"),)

    id = Column(Integer, primary_key=True)
    eleve_id = Column(Integer, ForeignKey("eleves.id", ondelete="CASCADE"), nullable=False, index=True)
    chapitre_id = Column(Integer, ForeignKey("chapitres.id", ondelete="CASCADE"), nullable=False)
    reponses = Column(Text, nullable=False, default="[]")
    maj_le = Column(DateTime, default=datetime.utcnow)
    envoye_le = Column(DateTime, nullable=True)   # dernier e-mail envoyé à l'admin

    eleve = relationship("Eleve", back_populates="reponses_chapitres")
    chapitre = relationship("Chapitre", back_populates="reponses_chapitres")


def sequence_chapitres(formation: Formation) -> list:
    # Tri explicite car selectinload ne garantit pas l'ordre des relationships.
    # Ordre affiché : modules triés par Module.ordre, puis chapitres triés par Chapitre.ordre dans chaque module.
    modules_tries = sorted(formation.modules, key=lambda m: (m.ordre, m.id))
    return [c for module in modules_tries for c in sorted(module.chapitres, key=lambda c: (c.ordre, c.id))]

def chapitre_dans_le_niveau(formation: Formation, niveau_eleve: int, chapitre) -> bool:
    if formation.nb_niveaux <= 1:
        return True
    if niveau_eleve < chapitre.module.niveau_requis:
        return False
    if niveau_eleve < chapitre.niveau_requis:
        return False
    return True

def chapitre_est_accessible(session, eleve_id: int, chapitre, acces=None) -> tuple:
    formation = chapitre.module.formation
    if acces is None:
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

def progression_pourcentage(session, eleve_id: int, formation, acces=None) -> float:
    if acces is None:
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
    date_evenement = Column(String(150)) # texte libre, ex: "Samedi 12 septembre 2026, 14h-17h"
    lieu = Column(String(300))           # ex: "Cabinet de Véranne (42520)"
    description_html = Column(Text)      # thème, déroulé, informations pratiques
    photo_url = Column(Text)             # optionnel, image encodée en base64
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


class Offre(Base):
    """Page d'offre publique avec paiement intégré (comptant ou acompte)."""
    __tablename__ = "offres"

    id = Column(Integer, primary_key=True)
    slug = Column(String(100), nullable=False, unique=True)
    nom = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    points_inclus = Column(Text, nullable=True)   # JSON list ["point1", "point2"]
    prix_total = Column(Numeric(10, 2), nullable=False)
    montant_acompte = Column(Numeric(10, 2), nullable=True)
    image_url = Column(Text, nullable=True)
    actif = Column(Boolean, default=True)
    cree_le = Column(DateTime, default=datetime.utcnow)
    formations_ids = Column(Text, nullable=True)  # JSON list [1, 2]
    badge = Column(String(200), nullable=True, default="Accompagnement féminin")


# ---------------------------------------------------------------------------
# AGENDA — Système de réservation natif (remplace Resalib)
# Toutes ces tables sont créées par Base.metadata.create_all (nouvelles tables).
# Aucune ALTER TABLE nécessaire pour ces modèles-ci.
# ---------------------------------------------------------------------------

class TypeSeance(Base):
    """Type de séance proposée par Laurence (ex : 'Séance cabinet 1h', 'Visio 1h30')."""
    __tablename__ = "agenda_types_seances"

    id = Column(Integer, primary_key=True)
    nom = Column(String(200), nullable=False)
    duree_minutes = Column(Integer, nullable=False, default=60)
    pause_apres_minutes = Column(Integer, nullable=False, default=0)  # temps de repos après séance
    # 'cabinet' | 'visio' | 'les_deux'
    modalite = Column(String(20), nullable=False, default="cabinet")
    couleur_hex = Column(String(10), default="#B8922A")
    description = Column(Text, nullable=True)
    actif = Column(Boolean, default=True)
    ordre = Column(Integer, default=0)

    plages = relationship("PlageDisponibilite", back_populates="type_seance")
    reservations = relationship("Reservation", back_populates="type_seance")


class Lieu(Base):
    """Lieu physique ou visio où se déroule une séance (cabinet, salle externe…)."""
    __tablename__ = "agenda_lieux"

    id = Column(Integer, primary_key=True)
    nom = Column(String(200), nullable=False)
    adresse = Column(Text, nullable=True)
    # 'cabinet' | 'visio' | 'autre'
    type_lieu = Column(String(20), nullable=False, default="cabinet")
    lien_visio = Column(String(500), nullable=True)   # URL Whereby / Jitsi / autre
    actif = Column(Boolean, default=True)

    plages = relationship("PlageDisponibilite", back_populates="lieu")
    reservations = relationship("Reservation", back_populates="lieu")


class PlageDisponibilite(Base):
    """Créneau horaire défini par Laurence dans son agenda (récurrent ou ponctuel).

    Exemple : "Mardis 9h-17h au cabinet" ou "Vendredi 14h le 5 nov uniquement".
    Les créneaux réels réservables sont calculés à partir de ces plages + durée du type de séance.
    """
    __tablename__ = "agenda_plages_disponibilites"

    id = Column(Integer, primary_key=True)
    type_seance_id = Column(Integer, ForeignKey("agenda_types_seances.id"), nullable=False)
    lieu_id = Column(Integer, ForeignKey("agenda_lieux.id"), nullable=False)
    # 0=lundi … 6=dimanche ; NULL = date_unique uniquement
    jour_semaine = Column(Integer, nullable=True)
    # Si ponctuel, la date spécifique (remplace jour_semaine)
    date_unique = Column(DateTime, nullable=True)
    heure_debut = Column(String(5), nullable=False)   # "09:00"
    heure_fin = Column(String(5), nullable=False)     # "17:00"
    # Pause méridienne optionnelle : exclut un bloc dans la journée
    pause_debut = Column(String(5), nullable=True)    # "12:00"
    pause_fin = Column(String(5), nullable=True)      # "13:30"
    # Période de validité pour les plages récurrentes (hebdo)
    # NULL = valable indéfiniment
    valide_du = Column(DateTime, nullable=True)
    valide_au = Column(DateTime, nullable=True)
    actif = Column(Boolean, default=True)
    cree_le = Column(DateTime, default=datetime.utcnow)

    type_seance = relationship("TypeSeance", back_populates="plages")
    lieu = relationship("Lieu", back_populates="plages")


class IndisponibiliteAgenda(Base):
    """Période durant laquelle Laurence n'est pas disponible.

    Bloque tous les créneaux sur la plage horaire indiquée,
    quel que soit le type de séance ou le lieu.
    Exemple : vacances, jour de repos, indisponibilité ponctuelle.
    """
    __tablename__ = "agenda_indisponibilites"

    id = Column(Integer, primary_key=True)
    date_debut = Column(DateTime, nullable=False)   # début de l'indispo
    date_fin = Column(DateTime, nullable=False)     # fin de l'indispo (incluse)
    motif = Column(String(200), nullable=True)      # libellé interne (non montré aux clientes)
    cree_le = Column(DateTime, default=datetime.utcnow)


class Reservation(Base):
    """Réservation d'un créneau par une cliente (ou créée manuellement par l'admin).

    Statuts : 'en_attente' (confirmée) | 'annulee' | 'realisee'
    Source   : 'publique' (formulaire /rendez-vous) | 'admin' (créée depuis le back-office)
    """
    __tablename__ = "agenda_reservations"

    id = Column(Integer, primary_key=True)
    token_annulation = Column(String(64), unique=True, nullable=False,
                              default=lambda: secrets.token_urlsafe(32))
    type_seance_id = Column(Integer, ForeignKey("agenda_types_seances.id"), nullable=True)
    lieu_id = Column(Integer, ForeignKey("agenda_lieux.id"), nullable=True)
    # Lien optionnel avec une élève existante (None si non inscrite)
    eleve_id = Column(Integer, ForeignKey("eleves.id"), nullable=True)
    # Coordonnées saisies dans le formulaire public (toujours renseignées)
    prenom = Column(String(100), nullable=False)
    nom = Column(String(100), nullable=False)
    email = Column(String(200), nullable=False)
    telephone = Column(String(30), nullable=True)
    message = Column(Text, nullable=True)
    # Date/heure du rendez-vous
    date_debut = Column(DateTime, nullable=False)
    date_fin = Column(DateTime, nullable=False)
    # 'en_attente' | 'annulee' | 'realisee'
    statut = Column(String(20), nullable=False, default="en_attente")
    # 'publique' | 'admin'
    source = Column(String(20), nullable=False, default="publique")
    # Lien visio unique généré à la réservation (pour séances visio)
    lien_visio_unique = Column(String(500), nullable=True)
    # Vrai si le .ics a bien été envoyé à la cliente
    ics_envoye = Column(Boolean, default=False)
    cree_le = Column(DateTime, default=datetime.utcnow)
    # Note interne admin (non visible par la cliente)
    note_admin = Column(Text, nullable=True)

    type_seance = relationship("TypeSeance", back_populates="reservations")
    lieu = relationship("Lieu", back_populates="reservations")
    eleve = relationship("Eleve", foreign_keys=[eleve_id])
    rappels = relationship("RappelEnvoye", back_populates="reservation",
                           cascade="all, delete-orphan")


class RappelEnvoye(Base):
    """Traçabilité des rappels email envoyés pour chaque réservation.

    Permet de ne pas renvoyer deux fois le même rappel (idempotence du cron).
    Types : 'confirmation' | 'rappel_j7' | 'rappel_j1' | 'suivi_post_seance'
    """
    __tablename__ = "agenda_rappels_envoyes"

    id = Column(Integer, primary_key=True)
    reservation_id = Column(Integer, ForeignKey("agenda_reservations.id",
                                                ondelete="CASCADE"), nullable=False)
    type_rappel = Column(String(30), nullable=False)
    envoye_le = Column(DateTime, default=datetime.utcnow)
    succes = Column(Boolean, default=True)

    reservation = relationship("Reservation", back_populates="rappels")
