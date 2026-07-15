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


## Mise a jour du 15 juillet, session acces au parcours boutique

Deux bugs supplementaires trouves et corriges: app/templates/eleve/catalogue.html et app/routes/inscription_publique.py avaient un caractere backtick parasite a la fin de leur nom de fichier reel sur GitHub. La page catalogue plantait en 500 et le formulaire d'inscription public n'etait pas enregistre dans main.py. Renommes proprement, inscription_publique.router ajoute a main.py, redeploye avec succes.

Parcours d'acces au LMS depuis le site vitrine, verifie en direct: sur menopause.html et initiations.html, le bouton Acceder a mon espace perso pointe vers slash reveil dest eleve, qui redirige vers slash eleve slash connexion. Cette page propose deja Se connecter et un lien vers slash eleve slash inscription. Il existe aussi une page slash portail deja construite mais pas reliee au site vitrine, avec deux boutons J'ai deja un compte et Je decouvre les formations, la version la plus proche de ce que Fabien avait imagine.

Catalogue: GET slash eleve slash catalogue et slash public slash catalogue fonctionnent maintenant, mais renvoient un tableau vide, aucune formation n'a de tarif actif configure cote admin pour l'instant. Le bouton Passer au paiement du catalogue appelle une route protegee par connexion; si un visiteur non connecte clique dessus, il recoit une erreur silencieuse au lieu d'etre redirige vers connexion ou inscription, point d'amelioration UX identifie mais pas corrige.


## Mise a jour du 15 juillet, session catalogue et tarifs admin

Fabien avait signale que l'onglet admin Catalogue et Tarifs ainsi que Codes promo restaient bloques sur Chargement. Deux bugs distincts ont ete trouves et corriges. Premier bug: les deux pages admin appelaient slash public slash catalogue pour lister les formations, mais cette route ne renvoie que les formations ayant deja au moins un tarif actif -- comme aucun tarif n'existait encore, la liste etait toujours vide et impossible a peupler (cercle vicieux). Correction: nouvel endpoint GET slash admin slash catalogue-complet dans app/routes/boutique_admin.py qui renvoie TOUTES les formations avec tous leurs tarifs quel que soit leur statut actif, plus image_url et description_courte. Les deux templates admin/catalogue_tarifs.html et admin/codes_promo.html ont ete modifies pour appeler ce nouvel endpoint. Deuxieme bug, plus sournois: les colonnes image_url et description_courte n'avaient en realite jamais ete ajoutees a la classe Formation dans app/models.py malgre le plan initial -- ce qui faisait planter le nouvel endpoint avec une erreur 500 des qu'il essayait de lire ces champs. Corrige en ajoutant les deux colonnes au modele, puis en ajoutant deux instructions ALTER TABLE ADD COLUMN IF NOT EXISTS dans app/migration_web_temporaire.py et en rappelant l'URL slash migration-colonnes slash laurence-setup-2026 pour les creer reellement dans la base Postgres -- une simple modification du modele Python ne suffit jamais a modifier une table deja existante en production, il faut toujours repasser par cette route de migration apres coup. Troisieme bug trouve en testant en conditions reelles: les deux pages plantaient encore avec une erreur ReferenceError appelApi is not defined. Cause: dans admin/base.html, le bloc contenu qui contient le script de la page enfant est place AVANT le script commun qui definit appelApi -- du coup un appel synchrone en bas du script de la page enfant s'executait avant que appelApi existe. Corrige en enveloppant l'appel initial dans document.addEventListener DOMContentLoaded dans les deux fichiers plutot que d'appeler la fonction directement -- a refaire pour toute future page admin qui suivrait ce meme modele et planterait de la meme facon. Les deux pages sont maintenant verifiees fonctionnelles en direct sur Render: Catalogue et Tarifs affiche les 5 formations existantes avec champs photo/description et bouton Ajouter un tarif, Codes promo affiche le formulaire de creation et Aucun code cree pour le moment.

Reste a faire pour la grosse mise a jour demandee par Fabien le 15 juillet: (1) verifier/finaliser dans l'UI les deux modes de promo -- promo visible avec prix barre (champs promo_active et promo_pourcentage deja geres par ouvrirEditionTarif dans catalogue_tarifs.html) versus promo cachee derriere un code (CodePromo, deja gere par codes_promo.html) -- le modele de donnees supporte deja les deux, il reste surtout a verifier l'affichage cote site eleve et vitrine. (2) Faire remonter les prix des formations et accompagnements du LMS sur le site vitrine statique (menopause.html, initiations.html, etc.) -- Fabien a precise que le site vitrine doit afficher les prix des formations ET des accompagnements qui sont dans le LMS. Attention: le site vitrine n'est PAS sur GitHub, deploiement uniquement via Netlify Drop, et les credits de build Netlify etaient epuises jusqu'au 1er aout (a reverifier aupres de Fabien avant de commencer ce chantier). (3) Aucun tarif n'existe encore dans la base pour aucune formation -- il faudra que Fabien (ou moi avec ses identifiants admin) cree au moins un tarif via le nouveau bouton Ajouter un tarif pour tester le parcours d'achat complet de bout en bout.


## Mise a jour du 15 juillet, session upload photo catalogue

Fabien a signale que le drag and drop de photo ne fonctionnait plus sur la page Catalogue et Tarifs, alors que ca marche ailleurs dans l'admin (Mon profil, Cercle de Femmes). Diagnostic: ces autres pages utilisent un vrai selecteur de fichier (input file plus FileReader qui convertit en base64), alors que le champ Photo de Catalogue et Tarifs etait un simple champ texte attendant qu'on colle une URL ou un base64 a la main -- aucune conversion de fichier n'existait sur cette page, donc glisser une image dessus ne faisait rien. Corrige dans app/templates/admin/catalogue_tarifs.html: ajout d'un vrai bouton Choisir un fichier plus une fonction previsualiserPhotoFormation (meme pattern FileReader que profil.html et cercle_femmes.html), avec apercu instantane et remplissage automatique du champ texte existant -- le bouton Enregistrer photo et texte et l'endpoint PUT slash admin slash formations slash id slash presentation n'ont pas eu besoin de changer. Verifie en direct sur Render: le selecteur de fichier apparait sur les 6 formations, et un fichier test convertit bien en base64 et affiche l'apercu. Fabien a par ailleurs deja cree des tarifs de test sur Le Temps des Essentielles (3 paliers cumulables) et L'art du pendule (tarif unique) -- reste a verifier l'affichage des deux modes de promo et a faire remonter les prix sur le site vitrine, toujours en attente de la confirmation des credits Netlify.
