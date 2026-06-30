# Intégration avec le site vitrine

Ce dossier explique comment relier le site vitrine (hébergé sur Netlify,
statique) à la plateforme de formation, **déjà en ligne** à l'adresse :

```
https://lms-formation.onrender.com
```

## Ce qui est prêt, avec la vraie adresse déjà intégrée

### 1. Lien discret vers l'administration (`lien_administration.html`)

À coller près des mentions légales du site, comme convenu au départ -- un
simple point "·" cliquable, sans texte explicite. Personne d'autre que
Laurence n'a de raison d'y prêter attention.

### 2. Bouton visible pour les élèves (`bouton_espace_eleve.html`)

Contrairement au lien admin, celui-ci doit être visible -- c'est la porte
d'entrée des élèves qui ont déjà payé. Deux présentations possibles dans le
même fichier : un bouton autonome (page d'accueil, page d'une formation) ou
un lien simple à glisser dans le menu de navigation principal.

### 3. Page d'explication "Mes formations" (`page_mes_formations.html`)

Optionnelle, mais recommandée : plutôt qu'un lien sec, un court texte qui
explique le concept avant le bouton de connexion. Peut devenir une vraie
page du site (`mes-formations.html`) si souhaité.

### 4. Lien retour, déjà construit côté plateforme

Une fois la variable d'environnement `URL_SITE_VITRINE` configurée sur
Render (voir ci-dessous), un lien "← Retour au site" apparaît automatiquement
en pied de page côté élève, et en bas de la barre latérale côté admin --
aucune modification du site nécessaire pour ce sens-là, c'est déjà actif
dans le code de la plateforme.

**Important** : tant que cette variable n'est pas configurée, ce lien reste
simplement invisible, sans rien casser -- testé et confirmé. Pas d'urgence
à la configurer.

## Pourquoi c'est aussi simple, techniquement

Un lien `<a href="...">` classique qui mène vers un autre site ne demande
aucune configuration technique particulière -- contrairement à des échanges
de données en arrière-plan entre deux domaines (API, formulaires AJAX), un
simple clic qui change de page n'a pas besoin d'autorisation spéciale (pas
de "CORS" à configurer pour ce cas précis).

## Étape facultative : un sous-domaine personnalisé

Pour remplacer `lms-formation.onrender.com` par une adresse plus mémorable,
par exemple `formation.laurence-mermet-bijon.fr` :

1. Dans le tableau de bord Render, page du service, section "Custom Domains",
   ajouter `formation.laurence-mermet-bijon.fr`
2. Render indique alors un enregistrement DNS à créer (type CNAME, pointant
   vers une adresse fournie par Render)
3. Aller chez l'hébergeur du nom de domaine (là où `laurence-mermet-bijon.fr`
   a été acheté), dans les réglages DNS, et ajouter cet enregistrement CNAME
4. Attendre la propagation (de quelques minutes à quelques heures)
5. Mettre à jour la variable d'environnement `URL_PLATEFORME` sur Render
   avec cette nouvelle adresse
6. Mettre à jour les 3 fichiers de ce dossier avec cette même adresse, à la
   place de `https://lms-formation.onrender.com`

Aucune urgence : l'adresse actuelle fonctionne déjà parfaitement, le
sous-domaine n'est qu'une question d'image, pas de fonctionnement.

## Pour activer le lien retour (étape 4 ci-dessus)

Sur Render, dans Environment Variables, ajouter :

| Variable | Valeur |
|---|---|
| `URL_SITE_VITRINE` | `https://laurence-mermet-bijon.fr` (ou l'adresse réelle du site) |

C'est tout -- le lien apparaît automatiquement, sans toucher au site.
