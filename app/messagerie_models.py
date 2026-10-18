"""
Messagerie élèves <-> Laurence (ajout du 18/10/2026).

UNIQUEMENT DE NOUVELLES TABLES : aucune table existante n'est modifiée. Elles sont
créées automatiquement au démarrage par Base.metadata.create_all (rien à ajouter
dans _MIGRATIONS_COLONNES). Les clés étrangères ont ondelete="CASCADE" : supprimer
une élève ou une formation supprime ses messages sans bloquer la suppression.

Principe :
- Une conversation = une élève x une formation. L'élève n'écrit qu'à Laurence.
- Une annonce = un message de Laurence à un groupe (toutes les actives d'une
  formation, ou une sélection selon l'avancement). Les destinataires sont figés au
  moment de l'envoi (table annonce_destinataires). Les réponses arrivent dans la
  conversation privée de chaque élève : les élèves ne se voient jamais entre elles.
- Un message privé = dans une conversation (de Laurence ou de l'élève).
- Les e-mails de notification sont envoyés par la tâche planifiée
  /cron/messagerie-notifications (colonnes notifie_le).
- Réglage « visible_eleves » (table parametres) : "test" = seuls les comptes test
  voient l'onglet Messages ; "tous" = toutes les élèves.
"""
from datetime import datetime

from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from .models import Base


class Parametre(Base):
    """Petits réglages modifiables depuis l'admin (clé -> valeur texte)."""
    __tablename__ = "parametres"

    cle = Column(String(100), primary_key=True)
    valeur = Column(Text, nullable=True)


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (UniqueConstraint("eleve_id", "formation_id", name="uniq_conversation_eleve_formation"),)

    id = Column(Integer, primary_key=True)
    eleve_id = Column(Integer, ForeignKey("eleves.id", ondelete="CASCADE"), nullable=False, index=True)
    formation_id = Column(Integer, ForeignKey("formations.id", ondelete="CASCADE"), nullable=False, index=True)
    cree_le = Column(DateTime, default=datetime.utcnow)
    dernier_message_le = Column(DateTime, default=datetime.utcnow, index=True)
    non_lu_admin = Column(Boolean, default=False)   # l'élève a écrit, Laurence n'a pas encore ouvert
    non_lu_eleve = Column(Boolean, default=False)   # Laurence a écrit, l'élève n'a pas encore ouvert

    messages = relationship("MessagePrive", back_populates="conversation", order_by="MessagePrive.cree_le",
                            cascade="all, delete-orphan", passive_deletes=True)


class MessagePrive(Base):
    __tablename__ = "messages_prives"

    id = Column(Integer, primary_key=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    auteur = Column(String(10), nullable=False)     # "admin" | "eleve"
    texte = Column(Text, nullable=False)
    cree_le = Column(DateTime, default=datetime.utcnow)
    notifier = Column(Boolean, default=True)        # False : pas d'e-mail pour ce message
    notifie_le = Column(DateTime, nullable=True)    # e-mail de notification envoyé

    conversation = relationship("Conversation", back_populates="messages")


class Annonce(Base):
    __tablename__ = "annonces"

    id = Column(Integer, primary_key=True)
    formation_id = Column(Integer, ForeignKey("formations.id", ondelete="CASCADE"), nullable=False, index=True)
    objet = Column(String(200), nullable=True)
    texte = Column(Text, nullable=False)
    cible = Column(String(300), nullable=True)      # description lisible : "Toutes les actives", "Module 3 terminé…"
    notifier = Column(Boolean, default=True)
    cree_le = Column(DateTime, default=datetime.utcnow, index=True)

    destinataires = relationship("AnnonceDestinataire", back_populates="annonce",
                                 cascade="all, delete-orphan", passive_deletes=True)


class AnnonceDestinataire(Base):
    __tablename__ = "annonce_destinataires"
    __table_args__ = (UniqueConstraint("annonce_id", "eleve_id", name="uniq_annonce_eleve"),)

    id = Column(Integer, primary_key=True)
    annonce_id = Column(Integer, ForeignKey("annonces.id", ondelete="CASCADE"), nullable=False, index=True)
    eleve_id = Column(Integer, ForeignKey("eleves.id", ondelete="CASCADE"), nullable=False, index=True)
    lu_le = Column(DateTime, nullable=True)
    notifie_le = Column(DateTime, nullable=True)

    annonce = relationship("Annonce", back_populates="destinataires")


def lire_parametre(session, cle: str, defaut: str = "") -> str:
    p = session.get(Parametre, cle)
    return p.valeur if p and p.valeur is not None else defaut


def ecrire_parametre(session, cle: str, valeur: str) -> None:
    p = session.get(Parametre, cle)
    if p is None:
        session.add(Parametre(cle=cle, valeur=valeur))
    else:
        p.valeur = valeur
    session.commit()


def messagerie_visible_pour(session, eleve) -> bool:
    """Interrupteur : tant que le réglage n'est pas « tous », seuls les comptes test
    voient l'onglet Messages (la messagerie arrive « éteinte » pour les élèves)."""
    if eleve is None:
        return False
    if lire_parametre(session, "messagerie_visible_eleves", "test") == "tous":
        return True
    return bool(eleve.compte_test)
