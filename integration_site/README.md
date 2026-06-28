# Intégration avec le site vitrine

Ce dossier explique comment relier le site vitrine (hébergé sur Netlify,
statique) à la plateforme de formation (ce serveur, hébergé sur Render).

## Ce qui est prêt dès maintenant

Le fichier `lien_administration.html` contient le code à coller dans le site,
près des mentions légales -- un lien discret vers la connexion administrateur.

**Pourquoi c'est aussi simple** : un lien `<a href="...">` classique qui mène
vers un autre site ne demande aucune configuration technique particulière --
contrairement à des échanges de données en arrière-plan entre deux domaines
(API, formulaires AJAX), un simple clic qui change de page n'a pas besoin
d'autorisation spéciale (pas de "CORS" à configurer pour ce cas précis).

## Étape à faire une fois le serveur en ligne : le sous-domaine

Une fois Render et Neon configurés (voir le README principal du projet) et
le serveur accessible à une adresse comme `https://lms-formation-laurence.onrender.com`,
deux options pour donner une adresse plus mémorable et professionnelle :

### Option A — Sous-domaine personnalisé (recommandé)

Exemple : `formation.laurence-mermet-bijon.fr`

1. Dans le tableau de bord Render, page du service, section "Custom Domains",
   ajouter `formation.laurence-mermet-bijon.fr`
2. Render indique alors un enregistrement DNS à créer (type CNAME, pointant
   vers une adresse fournie par Render)
3. Aller chez l'hébergeur du nom de domaine (là où `laurence-mermet-bijon.fr`
   a été acheté), dans les réglages DNS, et ajouter cet enregistrement CNAME
4. Attendre la propagation (de quelques minutes à quelques heures)
5. Mettre à jour la variable d'environnement `URL_PLATEFORME` sur Render avec
   cette nouvelle adresse
6. Mettre à jour le lien dans `lien_administration.html` (et le coller dans
   le site) avec cette même adresse

### Option B — Garder l'adresse fournie par Render

Plus rapide à mettre en place (rien à configurer côté DNS), mais moins
mémorable (`https://lms-formation-laurence.onrender.com`). Suffisant pour
commencer à tester en conditions réelles, le sous-domaine pouvant être ajouté
plus tard sans rien casser.

## Lien retour : de la plateforme vers le site

Si on veut aussi un chemin inverse (un bouton "Retour au site" depuis la
plateforme), il suffit d'ajouter un lien vers le site dans la topbar de
l'admin ou de l'élève -- pas de configuration technique nécessaire non plus,
pour la même raison (simple navigation par clic).
