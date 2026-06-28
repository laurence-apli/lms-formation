"""
Script à lancer UNE SEULE FOIS, juste après la mise en ligne du serveur, pour
créer le compte administrateur initial (Laurence). Sans ce script, il n'existe
aucun moyen de se connecter à l'administration -- c'est la "porte d'entrée"
posée à la main, une fois, en toute sécurité (jamais de compte par défaut
avec un mot de passe connu d'avance dans le code).

Usage (depuis la racine du projet, une fois les dépendances installées et
DATABASE_URL configurée) :

    python -m app.creer_premier_admin
"""
import getpass
from .database import SessionLocal, initialiser_base
from .models import Administrateur


def creer_premier_admin():
    initialiser_base()
    session = SessionLocal()

    if session.query(Administrateur).count() > 0:
        print("Un compte administrateur existe déjà. Ce script ne crée que le premier compte.")
        print("Pour ajouter un autre administrateur ou réinitialiser un mot de passe,")
        print("utilisez l'interface d'administration ou la procédure de réinitialisation par e-mail.")
        session.close()
        return

    print("=== Création du premier compte administrateur ===\n")
    nom = input("Nom : ").strip()
    prenom = input("Prénom : ").strip()
    email = input("E-mail de connexion : ").strip().lower()
    mot_de_passe = getpass.getpass("Mot de passe (au moins 8 caractères, ne s'affiche pas) : ")
    confirmation = getpass.getpass("Confirmez le mot de passe : ")

    if mot_de_passe != confirmation:
        print("\nLes deux mots de passe ne correspondent pas. Relancez le script.")
        session.close()
        return
    if len(mot_de_passe) < 8:
        print("\nLe mot de passe doit contenir au moins 8 caractères. Relancez le script.")
        session.close()
        return

    admin = Administrateur(nom=nom, prenom=prenom, email=email)
    admin.definir_mot_de_passe(mot_de_passe)
    session.add(admin)
    session.commit()

    print(f"\nCompte administrateur créé avec succès pour {prenom} {nom} ({email}).")
    print("Vous pouvez maintenant vous connecter sur la page d'administration.")
    session.close()


if __name__ == "__main__":
    creer_premier_admin()
