# Protocole de travail — LMS Laurence Mermet-Bijon

Ce fichier définit les règles à suivre à chaque intervention sur ce projet.
**Le respecter évite de casser ce qui fonctionne.**

---

## Avant toute modification : vérifications obligatoires

### 1. Identifier les fichiers impactés
- Lister tous les fichiers touchés par la modification demandée
- Identifier les fichiers qui *dépendent* de ces fichiers (templates qui appellent une route, routes qui utilisent un modèle, etc.)
- Signaler à l'utilisateur ce qui pourrait être affecté

### 2. Modifier un template HTML
- **Toujours lire la route API correspondante** avant d'écrire le JS
- Vérifier les noms de champs exacts retournés par l'API (ne jamais les supposer)
- Ne jamais inventer un nom de champ — si on n'est pas sûr, lire le fichier de route

### 3. Modifier un modèle SQLAlchemy (models.py)
- Toute nouvelle colonne ajoutée au modèle **doit aussi être ajoutée** dans `_MIGRATIONS_COLONNES` dans `app/database.py`
- Format : `"ALTER TABLE <table> ADD COLUMN IF NOT EXISTS <colonne> <type>"`
- Sans cette étape, la colonne existe dans le code mais pas en base → erreurs en production

### 4. Modifier une route
- Vérifier que tous les templates qui appellent cette route utilisent les bons champs
- Vérifier que le contrat de l'API (champs retournés) ne change pas sans mettre à jour les templates

---

## Avant de committer sur GitHub

- Lister les fichiers modifiés et décrire en une phrase ce que chaque changement fait
- Confirmer qu'aucune dépendance n'a été oubliée
- Rédiger un message de commit clair et précis

---

## Structure du projet — rappel rapide

```
app/
  main.py              — point d'entrée FastAPI, appelle initialiser_base()
  database.py          — connexion DB + migrations colonnes au démarrage
  models.py            — modèles SQLAlchemy (toute nouvelle colonne → database.py aussi)
  config.py            — variables d'environnement
  emails.py            — envoi d'emails (Brevo)
  pages.py             — routes pages HTML élève (catalogue, connexion, tableau de bord…)
  routes/
    auth.py            — connexion / déconnexion / mot de passe oublié
    inscription_publique.py — création de compte élève
    boutique_public.py — catalogue public + heartbeat
    espace_eleve.py    — espace élève connecté
    formations.py      — gestion formations (admin)
    eleves.py          — gestion élèves (admin)
    pages_admin.py     — pages admin
  templates/
    eleve/             — templates HTML côté élève
    admin/             — templates HTML côté admin
```

---

## Champs API importants à ne pas confondre

### `/public/catalogue` — champs tarif
| Champ | Description |
|---|---|
| `prix_base` | Prix original avant remise |
| `remise_montant` | Montant de la remise en € |
| `remise_pourcent` | Remise en % |
| `prix_final` | Prix à payer après remise |

> ⚠️ `prix_barre` et `prix` n'existent PAS dans cette API.

### Modèle `Eleve` — colonnes ajoutées via migration (pas via create_all)
- `nb_connexions` (INTEGER DEFAULT 0)
- `derniere_connexion` (TIMESTAMP)

---

## Règle générale

> En cas de doute sur la structure d'une réponse API ou d'un modèle,
> **lire le fichier source** avant d'écrire du code. Ne jamais supposer.

---

## Messagerie élèves ↔ Laurence (ajoutée le 18/10/2026)

- Modèles : `app/messagerie_models.py` — **nouvelles tables uniquement** (conversations,
  messages_prives, annonces, annonce_destinataires, parametres), créées par create_all.
- Routes : `app/routes/messagerie.py` (pages, API admin `/admin/messagerie/...`, API élève
  `/api/eleve/formations/{id}/messages`, tâche `/cron/messagerie-notifications`).
- Interrupteur : paramètre `messagerie_visible_eleves` (« test » = comptes test seuls,
  « tous » = toutes les élèves), réglable en haut de la page Messagerie de l'admin.
- Règle : une élève n'écrit qu'à Laurence ; sans accès à la formation, plus de messagerie.
- Les pièces jointes viendront avec le stockage Cloudflare R2 : ne JAMAIS stocker de fichier
  en base64 dans Neon pour la messagerie.

## Stockage des médias sur Cloudflare R2 (ajouté le 19/10/2026)

- Module : `app/stockage_r2.py` (signature SigV4 maison, pas de boto3). Bucket privé `lms-medias`.
- Actif seulement si les 4 variables Render `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`,
  `R2_SECRET_ACCESS_KEY`, `R2_BUCKET` existent ; sinon les imports restent en base64 comme avant.
- En base, un média R2 a `url = "r2:<clé>"` ; `est_r2` est un column_property (pas de migration).
- Lecture : `/medias/<type>/<id>/fichier` vérifie les droits puis redirige (307) vers une URL signée 4 h.
- Suppression d'un média : l'objet R2 n'est effacé que si aucun autre média (copie d'une
  formation dupliquée) ne pointe dessus.
- Vérifier la configuration : `GET /admin/stockage-r2/verifier` (connecté en admin).
