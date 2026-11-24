"""Accès automatique des comptes test à toutes les formations.

Règle (nov. 2026) : un compte test (Eleve.compte_test) a accès à TOUTES les
formations, actives ou inactives, dès leur création, sans paiement — pour
vérifier une formation avant de la rendre active.

- Un accès manquant est créé au niveau maximum de la formation (nb_niveaux).
- Un accès déjà existant n'est jamais modifié (on peut régler son niveau à la main
  pour tester l'affichage d'un niveau précis).
- Aucun email n'est envoyé.
"""
from typing import Optional

from sqlalchemy.orm import Session

from .models import AccesFormation, Eleve, Formation


def donner_acces_comptes_test(session: Session, formation_id: Optional[int] = None,
                              eleve_id: Optional[int] = None) -> int:
    """Crée les accès manquants (comptes test × formations). Ne fait pas de commit.
    formation_id / eleve_id limitent le travail à une formation ou à une élève.
    Renvoie le nombre d'accès créés."""
    q_eleves = session.query(Eleve).filter(Eleve.compte_test.is_(True))
    if eleve_id is not None:
        q_eleves = q_eleves.filter(Eleve.id == eleve_id)
    eleves = q_eleves.all()
    if not eleves:
        return 0

    q_formations = session.query(Formation)
    if formation_id is not None:
        q_formations = q_formations.filter(Formation.id == formation_id)
    formations = q_formations.all()

    existants = {
        (a.eleve_id, a.formation_id)
        for a in session.query(AccesFormation.eleve_id, AccesFormation.formation_id)
        .filter(AccesFormation.eleve_id.in_([e.id for e in eleves])).all()
    }
    nb = 0
    for eleve in eleves:
        for formation in formations:
            if (eleve.id, formation.id) in existants:
                continue
            session.add(AccesFormation(eleve_id=eleve.id, formation_id=formation.id,
                                       niveau=formation.nb_niveaux or 1))
            nb += 1
    return nb
