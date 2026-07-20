"""
Point d'entrée principal du serveur de la plateforme de formation.
"""
import logging
from fastapi import Depends, FastAPI
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from .config import SECRET_KEY
from .database import initialiser_base, obtenir_session
from .routes import auth, formations, import_word, eleves, espace_eleve, profil
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
app.include_router(profil.router)
app.include_router(pages.router)
app.include_router(pages_admin.router)
app.include_router(setup_temporaire.router)
app.include_router(migration_web_temporaire.router)



@app.on_event("startup")
def au_demarrage():
    initialiser_base()


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
def ping(db: Session = Depends(obtenir_session)):
    db.execute(text("SELECT 1"))
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
