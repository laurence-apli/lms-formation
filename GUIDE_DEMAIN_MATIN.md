# Guide pas à pas — Mise en ligne (à faire demain matin)

Ce guide est conçu pour que tu puisses tout faire seule, étape par étape,
sans avoir besoin de poser de questions. Une fois que tu as fait CES 4 ÉTAPES,
dis-moi "c'est fait" dans la conversation et je m'occupe de tout le reste
(créer ton compte administrateur, vérifier que tout fonctionne).

Temps estimé : 15-20 minutes.

---

## ÉTAPE 0 — Créer le dépôt GitHub (probablement nécessaire)

Ton compte GitHub existe déjà (`laurence-apli`), mais le code de la
plateforme n'a probablement pas encore été déposé dedans. Sans ça, Render
ne pourra pas trouver le code à l'étape 2.

1. Va sur **https://github.com**, connecte-toi avec ton compte
2. Clique sur le bouton **"+"** en haut à droite, puis **"New repository"**
3. Donne un nom, par exemple : `lms-formation`
4. Laisse-le en **"Private"** (privé — personne d'autre ne doit voir ce code)
5. Ne coche aucune case (pas de README, pas de .gitignore -- on les a déjà)
6. Clique sur **"Create repository"**
7. GitHub affiche alors une page avec des instructions et une adresse du type
   `https://github.com/laurence-apli/lms-formation.git` — **garde cette page ouverte**

À ce stade, il faut ENVOYER les fichiers du projet vers ce dépôt vide. C'est
l'étape la plus technique : si tu as un terminal/ligne de commande sous la
main et un peu d'aisance, GitHub propose des commandes à copier-coller sur
cette même page ("…or push an existing repository from the command line").

**Si ça te semble trop technique : ne fais rien de plus ici.** Dis-moi
simplement "j'ai créé le dépôt, voici son adresse : [...]" et je préparerai
le nécessaire pour la suite à ce moment-là -- on trouvera la façon la plus
simple de déposer le code une fois que tu seras disponible pour suivre les
indications ensemble.

✅ Étape 0 terminée quand le dépôt vide existe sur GitHub, même sans le code dedans encore.

---

## ÉTAPE 1 — Créer la base de données (Neon)

1. Va sur **https://neon.tech**
2. Clique sur **"Sign up"** (en haut à droite)
3. Inscris-toi avec ton e-mail (ou directement avec ton compte GitHub déjà créé — c'est le plus simple, un seul clic)
4. Une fois connectée, clique sur **"Create a project"** (ou "New Project")
5. Donne un nom au projet, par exemple : `lms-laurence`
6. Choisis une région proche de la France si demandé (ex: "Europe")
7. Clique sur **"Create project"**
8. Une fois créé, Neon affiche une **chaîne de connexion** qui commence par `postgresql://...` — c'est une longue ligne de texte avec des lettres et chiffres
9. **Copie cette ligne complète** et colle-la dans un endroit sûr (ton gestionnaire de mots de passe, ou un fichier texte que tu me montreras) — on en aura besoin à l'étape 3

✅ Étape 1 terminée quand tu as cette ligne `postgresql://...` copiée de côté.

---

## ÉTAPE 2 — Créer le service web (Render)

1. Va sur **https://render.com**
2. Clique sur **"Get Started"** ou **"Sign up"**
3. Inscris-toi avec ton compte **GitHub** (le plus simple — un clic, ça relie directement les deux)
4. Une fois connectée, clique sur **"New +"** puis **"Web Service"**
5. Render demande de choisir un dépôt GitHub — choisis celui où le code de la plateforme a été déposé (si le code n'est pas encore sur GitHub, voir la note ci-dessous)
6. Render devrait détecter automatiquement le fichier `render.yaml` du projet et proposer une configuration pré-remplie — laisse-le faire
7. Donne un nom au service si demandé (ex: `lms-formation-laurence`)
8. Clique sur **"Create Web Service"**

⚠️ **Si le code n'est pas encore sur GitHub** : il faut d'abord créer un
"dépôt" (repository) sur GitHub et y déposer les fichiers du projet. Dis-le
moi demain et je te guiderai pour cette étape précise — ou si tu sais déjà
comment faire, n'hésite pas.

✅ Étape 2 terminée quand Render affiche "Deploying..." ou "Live" pour ton service.

---

## ÉTAPE 3 — Configurer les variables (dans Render)

1. Sur la page de ton service Render, va dans l'onglet **"Environment"**
2. Trouve la ligne **`DATABASE_URL`** et colle la chaîne `postgresql://...` copiée à l'étape 1
3. Clique sur **"Save Changes"** — Render va redémarrer le service automatiquement
4. Laisse les autres variables comme elles sont pour l'instant (`RESEND_API_KEY` vide, c'est normal)

✅ Étape 3 terminée quand "Save Changes" a été cliqué.

---

## ÉTAPE 4 — Vérifier que ça tourne

1. Sur la page du service Render, en haut, il y a une adresse du type `https://lms-formation-laurence.onrender.com`
2. Clique sur cette adresse (ou copie-la dans un nouvel onglet)
3. Si tu vois un petit message du type `{"message":"Serveur de la plateforme de formation -- en ligne."}`, **c'est gagné** — le serveur fonctionne.
4. Si tu vois une page d'erreur, ne t'inquiète pas — copie-moi le message d'erreur ou fais une capture d'écran, je m'occuperai de tout corriger.

✅ **C'est tout ce que tu as à faire.** Une fois ces 4 étapes terminées
(ou même si quelque chose n'a pas marché), dis-moi "c'est fait" et je
m'occupe de la suite : créer ton compte administrateur, vérifier chaque
fonctionnalité, corriger ce qui doit l'être.

---

## Ce que je ferai ensuite, sans que tu aies à intervenir

- Lancer le script de création de ton compte administrateur
- Tester toutes les pages (formations, élèves, import Word, diplômes, profil)
  directement sur le serveur en ligne, comme je l'ai déjà fait en local
- Vérifier que les e-mails (encore simulés, visibles dans les "Logs" de Render)
  fonctionnent bien
- Préparer la suite : sous-domaine personnalisé, lien depuis le site vitrine
