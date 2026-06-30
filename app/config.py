"""
Configuration centrale du serveur.

Toutes les valeurs sensibles (mot de passe de la base de données, clé secrète
de session, clé de l'API d'envoi d'e-mails) viennent de VARIABLES D'ENVIRONNEMENT
-- jamais écrites en dur dans le code. C'est Render qui les fournira une fois
le service configuré (Render Dashboard > Environment).

En développement local (sur cet ordinateur, avant la mise en ligne), on utilise
des valeurs de repli simples pour pouvoir tester sans tout configurer.
"""
import os

# --- Base de données ---
# En production (Render) : DATABASE_URL sera fournie automatiquement par Neon,
# au format postgresql://utilisateur:motdepasse@hôte/nom_base
# En local (tests) : on retombe sur un simple fichier SQLite, pas besoin
# d'installer PostgreSQL sur cet ordinateur pour développer.
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///lms_local.db")

# --- Sécurité des sessions (cookies de connexion) ---
# Cette clé sert à signer les cookies de session, pour qu'on ne puisse pas les
# falsifier. DOIT être une vraie valeur secrète et unique en production --
# Render la générera et la fournira comme variable d'environnement.
SECRET_KEY = os.environ.get("SECRET_KEY", "cle-de-developpement-local-a-ne-jamais-utiliser-en-production")

# --- Envoi d'e-mails (Resend) ---
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
EMAIL_EXPEDITEUR = os.environ.get("EMAIL_EXPEDITEUR", "formation@laurence-mermet-bijon.fr")

# --- Adresse publique de la plateforme (pour construire les liens dans les e-mails) ---
URL_PLATEFORME = os.environ.get("URL_PLATEFORME", "http://localhost:8000")

# Adresse du site vitrine (laurence-mermet-bijon.fr), utilisée pour le lien
# "Retour au site" affiché en pied de page côté élève et admin. Valeur de
# repli vide tant que cette variable n'est pas configurée sur Render --
# dans ce cas, le lien retour reste simplement masqué plutôt que de pointer
# vers une adresse incorrecte.
URL_SITE_VITRINE = os.environ.get("URL_SITE_VITRINE", "")

# --- Durée de validité des liens envoyés par e-mail ---
DUREE_VALIDITE_TOKEN_HEURES = 48

# --- Mode développement : active des messages d'erreur détaillés, jamais en production ---
MODE_DEVELOPPEMENT = os.environ.get("MODE_DEVELOPPEMENT", "true").lower() == "true"
