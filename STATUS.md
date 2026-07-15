## STATUS.md, a lire en debut de session

Resume de l'etat du projet pour toute IA ou humain qui reprend le travail apres une coupure de conversation. A mettre a jour a la fin de chaque session de travail significative.

## Contexte

Fabien gere le travail technique pour Laurence Mermet-Bijon, praticienne en soins energetiques, Veranne 42520. Deux projets lies: le site vitrine statique laurence-mermet-bijon.fr sur Netlify Drop, non lie a GitHub, et ce depot, la plateforme LMS FastAPI et SQLAlchemy sur Render, lms-formation.onrender.com, base Neon Postgres.

## Etat au 15 juillet 2026

Module boutique, 16 points du plan initial: complet et deploye. Tarifs, codes promo, paiement Stripe, catalogue public, montee de niveau. Fichiers concernes: app slash routes slash boutique_models.py, boutique_public.py, boutique_paiement.py, boutique_admin.py, plus templates admin catalogue_tarifs.html et codes_promo.html, plus inscription et portail eleve.

Piege rencontre et corrige le 15 juillet: les routeurs boutique_public, boutique_paiement, boutique_admin n'etaient pas enregistres dans app slash main.py, aucun app.include_router pour eux, donc toutes les routes boutique renvoyaient 404 malgre du code correct. Egalement stripe manquait de requirements.txt, ce qui a fait planter le premier deploiement correctif, exit status 1. Corrige par les commits e5fe412 puis 2e516e5.

A tester si pas deja fait: GET slash public slash catalogue, routes admin tarifs et admin codes-promo qui necessitent admin_connecte, flux de paiement Stripe qui necessite STRIPE_SECRET_KEY et STRIPE_WEBHOOK_SECRET sur Render, pas encore configure tant que le compte Stripe n'est pas cree.

Alma paiement en 3 fois: code pret via le champ autoriser_3x, a activer seulement quand le compte marchand Alma existera.

## Autres chantiers en cours, voir aussi la memoire de projet Claude.ai

Site vitrine: batch de corrections en attente pour le prochain deploiement Netlify, credits epuises jusqu'au 1er aout 2026. OVH: transfert de domaine en cours depuis Wix, bloque la verification Resend pour les emails. Attestation de fin de formation: mockup HTML valide, backend pas encore fait, reste a faire reportlab, colonne date_fin_formation, bouton telechargement. Moteur d'import Word, word_to_web.py: prototype valide localement, pas encore integre au pipeline complet.

## A savoir avant de modifier ce depot

Deploiement: push sur main declenche un auto-deploy Render. Free tier avec hibernation apres inactivite, environ 50 secondes de reveil sur la premiere requete apres veille.

Workflow d'edition prefere par Fabien: interface web GitHub, bouton crayon ou Add file, jamais de terminal ou de CLI git de son cote.

Piege a eviter: avant de faire confiance au nom d'un fichier fourni par Fabien en upload, verifier le commentaire a placer dans en tete du fichier. Episode reel de decalage entre noms de fichiers exportes et contenu reel sur un lot de 16 fichiers, voir conversation du 15 juillet 2026. Le commentaire interne fait foi, jamais le nom du fichier seul.

Laurence n'utilise ni chakras ni lithotherapie, ne jamais en parler dans le contenu produit pour elle. Attestation de fin de formation est le terme legalement correct, jamais diplome.
