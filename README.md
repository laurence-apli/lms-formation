# Plateforme de formation — Laurence Mermet-Bijon

Serveur de la plateforme de formation en ligne, reliée au site vitrine.

## Ce que contient ce projet

- `app/models.py` — structure des données (formations, élèves, accès, niveaux, accompagnement)
- `app/word_to_web.py` — moteur d'import Word → page web (déjà testé et validé)
- `app/routes/` — toutes les routes du serveur (connexion, formations, élèves, espace élève)
- `app/emails.py` — envoi d'e-mails (première connexion, réinitialisation de mot de passe)
- `app/creer_premier_admin.py` — script à lancer une seule fois pour créer le premier compte administrateur

## Mise en ligne — étapes à suivre dans l'ordre

### 1. Créer la base de données (Neon)

1. Aller sur [neon.tech](https://neon.tech), créer un compte gratuit
2. Créer un nouveau projet (ex: "lms-laurence")
3. Copier l'URL de connexion fournie (commence par `postgresql://...`)
4. La garder de côté pour l'étape 3

### 2. Créer le service web (Render)

1. Aller sur [render.com](https://render.com), créer un compte gratuit
2. Connecter le compte GitHub où ce code est déposé
3. Créer un nouveau "Web Service", pointant vers ce dépôt
4. Render détecte automatiquement le fichier `render.yaml` et propose la configuration

### 3. Configurer les variables d'environnement (dans le tableau de bord Render)

| Variable | Valeur |
|---|---|
| `DATABASE_URL` | l'URL copiée depuis Neon à l'étape 1 |
| `SECRET_KEY` | générée automatiquement par Render, rien à faire |
| `RESEND_API_KEY` | laisser vide pour l'instant (les e-mails seront simulés dans les journaux) |
| `URL_PLATEFORME` | l'adresse définitive de la plateforme, une fois connue (ex: `https://formation.laurence-mermet-bijon.fr`) |

⚠️ **Important** : `URL_PLATEFORME` doit être configurée correctement dès le
départ (même avec l'adresse provisoire fournie par Render si le sous-domaine
n'est pas encore prêt). Sans cela, les liens envoyés par e-mail (première
connexion, réinitialisation de mot de passe) pointeraient vers une adresse
incorrecte et ne fonctionneraient pas, aussi bien pour Laurence que pour les
élèves. Mettre à jour cette variable de nouveau si l'adresse change plus tard
(passage à un sous-domaine personnalisé par exemple).

### 4. Créer le premier compte administrateur

Une fois le service démarré sur Render, ouvrir un "Shell" depuis le tableau de bord Render (bouton disponible sur la page du service), puis lancer :

```
python -m app.creer_premier_admin
```

Suivre les instructions (nom, prénom, e-mail, mot de passe). Ce script ne peut être utilisé qu'une seule fois — il refuse de créer un second compte par-dessus.

### 5. Activer l'envoi réel d'e-mails (quand prêt)

1. Créer un compte sur [resend.com](https://resend.com) (gratuit)
2. Récupérer la clé API
3. La renseigner dans la variable `RESEND_API_KEY` sur Render
4. Redéployer le service (Render le fait automatiquement après un changement de variable)

Avant cette étape, tous les e-mails (première connexion, réinitialisation de mot de passe) sont visibles dans l'onglet "Logs" de Render au lieu d'être réellement envoyés — la plateforme reste pleinement utilisable pour tester.

### 6. Relier au site vitrine

Une fois la plateforme en ligne et son adresse définitive connue, ajouter un sous-domaine (ex: `formation.laurence-mermet-bijon.fr`) qui pointe vers Render, depuis les réglages DNS du nom de domaine.

## Limite connue (plan gratuit Render)

Si le service n'a reçu aucune visite depuis 15 minutes, il se met en veille. La visite suivante prend 30 à 60 secondes à charger avant de répondre normalement. C'est un compromis accepté pour rester gratuit — un écran d'attente sera affiché côté élève pendant ce délai.

## Limite de taille pour l'import Word (4 Mo par fichier)

Le plan gratuit de Render ne dispose que de 512 Mo de RAM au total pour tout
le serveur. Le traitement d'un fichier Word (extraction du texte, des images,
mise en forme) peut consommer, mesuré en conditions réelles, jusqu'à environ
50 fois la taille du fichier en mémoire pendant l'import. Au-delà de 4 Mo,
le risque de faire planter le service entier (pas seulement l'import en
cours) devient réel. Si Laurence a besoin d'importer un document plus long,
la bonne pratique est de le découper en plusieurs chapitres -- ce qui est
de toute façon une meilleure organisation pédagogique. Si ce besoin devient
fréquent, augmenter cette limite supposera de passer à un plan Render payant
avec plus de RAM (voir `app/routes/import_word.py`, variable `TAILLE_MAX_OCTETS`).
