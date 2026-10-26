"""
Point d'entrée principal du serveur de la plateforme de formation.
"""
import logging
from fastapi import FastAPI
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from .config import SECRET_KEY
from .database import initialiser_base
from .routes import auth, formations, import_word, eleves, espace_eleve, profil, medias_fichiers, rapport_hebdo
from .routes import offres_admin, offres_publiques
from .routes import live as live_routes
from . import pages
from . import pages_admin
from . import setup_temporaire
from . import migration_web_temporaire

# Configuration du logging : sans ceci, les messages (notamment la simulation
# des e-mails tant que RESEND_API_KEY n'est pas configurée) ne s'afficheraient
# jamais dans les journaux du serveur -- testé et confirmé manquant.
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")

app = FastAPI(title="Plateforme de formation — Laurence Mermet-Bijon")
templates = Jinja2Templates(directory="app/templates")

# Sessions par cookie signé (jamais d'identifiant en clair dans l'URL ou le HTML)
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

app.include_router(auth.router)
app.include_router(formations.router)
app.include_router(import_word.router)
app.include_router(eleves.router)
app.include_router(espace_eleve.router)
app.include_router(medias_fichiers.router)
app.include_router(rapport_hebdo.router)
app.include_router(profil.router)
app.include_router(pages.router)
app.include_router(pages_admin.router)
app.include_router(setup_temporaire.router)
app.include_router(migration_web_temporaire.router)
app.include_router(live_routes.router)



from urllib.parse import quote
from fastapi import Request
from fastapi.responses import RedirectResponse
from fastapi.exception_handlers import http_exception_handler as _gestion_par_defaut
from starlette.exceptions import HTTPException as StarletteHTTPException


@app.exception_handler(StarletteHTTPException)
async def rediriger_vers_connexion(request: Request, exc: StarletteHTTPException):
    """Page HTML ouverte sans être connecté (ex. lien « Lire et répondre » d'un e-mail) :
    au lieu d'afficher {"detail":"Connexion requise."}, on envoie vers la page de
    connexion, qui ramène ensuite sur la page demandée. Les appels d'API (fetch)
    gardent leur réponse JSON habituelle."""
    if exc.status_code == 401 and request.method == "GET":
        chemin = request.url.path
        cible = chemin + (("?" + request.url.query) if request.url.query else "")
        if chemin.startswith("/eleve/"):
            return RedirectResponse("/eleve/connexion?suite=" + quote(cible, safe="/"), status_code=303)
        if chemin.startswith("/admin/page/"):
            request.session["apres_connexion_admin"] = cible
            return RedirectResponse("/admin/connexion", status_code=303)
    return await _gestion_par_defaut(request, exc)


@app.on_event("startup")
def au_demarrage():
    initialiser_base()
    # Messagerie ouverte à toutes les élèves par défaut (plus seulement les comptes test)
    from .database import SessionLocal
    from .messagerie_models import lire_parametre, ecrire_parametre
    try:
        session = SessionLocal()
        valeur_actuelle = lire_parametre(session, "messagerie_visible_eleves", "tous")
        if valeur_actuelle != "tous":
            ecrire_parametre(session, "messagerie_visible_eleves", "tous")
        session.close()
    except Exception:
        pass  # table pas encore créée au tout premier démarrage


@app.get("/")
def racine():
    return {"message": "Serveur de la plateforme de formation -- en ligne."}


@app.get("/sante")
def verification_sante():
    """Route simple pour vérifier que le serveur répond -- utile pour Render
    et pour tout outil de supervision."""
    return {"statut": "ok"}

from .routes import cercle_femmes
app.include_router(cercle_femmes.router)

@app.get("/ping")
def ping():
    return {"ok": True}


from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://laurence-mermet-bijon.fr"],
    allow_methods=["GET"],
)

from .routes import boutique_public, boutique_paiement, boutique_admin
app.include_router(boutique_public.router)
app.include_router(boutique_paiement.router)
app.include_router(boutique_admin.router)

from .routes import inscription_publique
app.include_router(inscription_publique.router)

# Messagerie élèves <-> Laurence (nouvelles tables uniquement, voir app/messagerie_models.py)
from .routes import messagerie
app.include_router(messagerie.router)
app.include_router(messagerie.admin_router)
# Offres publiques et paiements
app.include_router(offres_admin.router, prefix="/admin", tags=["offres-admin"])
app.include_router(offres_publiques.router, tags=["offres-publiques"])

# Agenda natif (remplace Resalib)
from .routes.agenda import (
    admin_router as agenda_admin_router,
    public_router as agenda_public_router,
    api_router as agenda_api_router,
    cron_router as agenda_cron_router,
    webhook_router as agenda_webhook_router,
)
app.include_router(agenda_admin_router)
app.include_router(agenda_public_router)
app.include_router(agenda_api_router)
app.include_router(agenda_cron_router)
app.include_router(agenda_webhook_router)
