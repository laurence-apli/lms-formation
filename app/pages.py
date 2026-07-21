"""
Routes qui servent les vraies pages HTML visuelles, en réutilisant les routes
API (JSON) déjà existantes comme source de données via JavaScript côté client.

Séparation volontaire : les routes dans espace_eleve.py / eleves.py /
formations.py restent de pures API (testées indépendamment), ces routes-ci ne
font que choisir QUELLE page HTML afficher et avec QUELLES données de départ.
"""
import base64
from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .database import obtenir_session
from .models import Eleve, Formation, Administrateur, TokenAuthEleve, TokenAuthAdmin, AccesFormation, progression_pourcentage
from .routes.auth import eleve_connecte
from .routes.boutique_models import Commande
from .config import URL_SITE_VITRINE

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

def _profil_pour_affichage(session: Session) -> dict:
    """Le profil de l'administratrice, affiché dans la topbar élève (logo, nom)
    et dans la colonne de gauche de l'écran de formation (photo).

    CORRECTION TRANSFERT NEON : au lieu d'embarquer les images base64 (logo,
    photo) directement dans la réponse HTML de chaque page, on renvoie des URLs
    vers les endpoints dédiés /api/profil/logo et /api/profil/photo. Ces
    endpoints ajoutent un Cache-Control d'une heure : le navigateur de l'élève
    ne télécharge les images qu'une seule fois par session, au lieu de les
    recevoir complètes dans chaque page HTML."""
    admin = session.query(Administrateur).first()
    if admin is None:
        return {"nom": "", "prenom": "", "email": "", "logo_url": None, "photo_url": None}
    return {
        "nom": admin.nom,
        "prenom": admin.prenom,
        "email": admin.email,
        "logo_url": "/api/profil/logo" if admin.logo_url else None,
        "photo_url": "/api/profil/photo" if admin.photo_url else None,
    }


# ---------------------------------------------------------------------------
# Endpoints images profil admin — servis séparément avec cache navigateur
# ---------------------------------------------------------------------------

def _servir_image_base64(data_uri, cache_seconds=3600):
    """Convertit une data URI base64 stockée en base de données en réponse
    image HTTP avec en-tête Cache-Control. Le navigateur met l'image en cache
    et ne la retélécharge pas à chaque navigation de l'élève."""
    if not data_uri:
        raise HTTPException(status_code=404, detail="Image non disponible.")
    if data_uri.startswith("data:"):
        try:
            header, encoded = data_uri.split(",", 1)
            content_type = header.split(";")[0].replace("data:", "") or "image/png"
            image_bytes = base64.b64decode(encoded)
        except Exception:
            raise HTTPException(status_code=500, detail="Image corrompue.")
    else:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url=data_uri)
    return Response(
        content=image_bytes,
        media_type=content_type,
        headers={"Cache-Control": f"public, max-age={cache_seconds}"},
    )


@router.get("/api/profil/logo")
def api_profil_logo(session: Session = Depends(obtenir_session)):
    """Sert le logo de l'administratrice sous forme d'image HTTP mise en cache."""
    admin = session.query(Administrateur).first()
    return _servir_image_base64(admin.logo_url if admin else None)


@router.get("/api/profil/photo")
def api_profil_photo(session: Session = Depends(obtenir_session)):
    """Sert la photo de l'administratrice sous forme d'image HTTP mise en cache."""
    admin = session.query(Administrateur).first()
    return _servir_image_base64(admin.photo_url if admin else None)

@router.get("/eleve/connexion", response_class=HTMLResponse)
def page_connexion(request: Request):
    return templates.TemplateResponse(request, "eleve/connexion.html", {})

@router.get("/admin/connexion", response_class=HTMLResponse)
def page_connexion_admin(request: Request):
    return templates.TemplateResponse(request, "admin/connexion.html", {})

@router.get("/admin/definir-mot-de-passe/{token}", response_class=HTMLResponse)
def page_definir_mot_de_passe_admin(request: Request, token: str, session: Session = Depends(obtenir_session)):
    token_obj = session.query(TokenAuthAdmin).filter_by(token=token).first()
    token_valide = token_obj is not None and token_obj.est_valide()
    return templates.TemplateResponse(
        request, "admin/definir_mot_de_passe.html", {"token_valide": token_valide},
    )

@router.get("/eleve/definir-mot-de-passe/{token}", response_class=HTMLResponse)
def page_definir_mot_de_passe(request: Request, token: str, session: Session = Depends(obtenir_session)):
    token_obj = session.query(TokenAuthEleve).filter_by(token=token).first()
    token_valide = token_obj is not None and token_obj.est_valide()
    eleve_prenom = ""
    eleve_email = ""
    if token_valide:
        eleve = session.get(Eleve, token_obj.eleve_id)
        if eleve:
            eleve_prenom = eleve.prenom
            eleve_email = eleve.email
    return templates.TemplateResponse(
        request, "eleve/definir_mot_de_passe.html",
        {"token_valide": token_valide, "token": token,
         "eleve_prenom": eleve_prenom, "eleve_email": eleve_email},
    )

@router.get("/eleve/tableau-de-bord", response_class=HTMLResponse)
def page_tableau_de_bord(
    request: Request, eleve: Eleve = Depends(eleve_connecte), session: Session = Depends(obtenir_session),
):
    formations_acquises = []
    for acces in eleve.acces_formations:
        formation = acces.formation
        if not formation.actif:
            continue
        formations_acquises.append({
            "id": formation.id, "titre": formation.titre, "couleur": formation.couleur,
            "image_url": formation.image_url,
            "nb_niveaux": formation.nb_niveaux, "ordre_affichage": formation.ordre_affichage, "niveau": acces.niveau,
            "progression": progression_pourcentage(session, eleve.id, formation),
        })
    formations_acquises.sort(key=lambda f: (0 if f["progression"] > 0 else 1, f["ordre_affichage"]))
    ids_acquis = {f["id"] for f in formations_acquises}
    formations_disponibles = [
        {"id": f.id, "titre": f.titre, "couleur": f.couleur, "image_url": f.image_url, "ordre_affichage": f.ordre_affichage}
        for f in session.query(Formation).filter_by(actif=True).order_by(Formation.ordre_affichage, Formation.id).all()
        if f.id not in ids_acquis
    ]
    return templates.TemplateResponse(
        request, "eleve/tableau_de_bord.html",
        {
            "eleve": eleve,
            "formations_acquises": formations_acquises,
            "formations_disponibles": formations_disponibles,
            "profil": _profil_pour_affichage(session),
            "url_site_vitrine": URL_SITE_VITRINE,
        },
    )

@router.get("/eleve/voir-formation/{formation_id}", response_class=HTMLResponse)
def page_formation(
    request: Request, formation_id: int, eleve: Eleve = Depends(eleve_connecte),
    session: Session = Depends(obtenir_session),
):
    formation = session.get(Formation, formation_id)
    if formation is None:
        raise HTTPException(status_code=404, detail="Formation introuvable.")
    acces = (
        session.query(AccesFormation)
        .filter_by(eleve_id=eleve.id, formation_id=formation_id)
        .first()
    )
    if acces is None:
        raise HTTPException(status_code=403, detail="Vous n'avez pas accès à cette formation.")
    if not formation.actif:
        raise HTTPException(status_code=403, detail="Cette formation n'est actuellement pas disponible.")
    return templates.TemplateResponse(
        request, "eleve/formation.html",
        {"eleve": eleve, "formation": formation, "profil": _profil_pour_affichage(session), "url_site_vitrine": URL_SITE_VITRINE},
    )

@router.get("/eleve/paiement-confirme", response_class=HTMLResponse)
def page_paiement_confirme(
    request: Request, session_id: str = "", eleve: Eleve = Depends(eleve_connecte),
    session: Session = Depends(obtenir_session),
):
    """Page affichée juste après le paiement (réel via Stripe, ou simulé --
    voir MODE_SIMULATION_PAIEMENT dans boutique_paiement.py). Ne fait AUCUN
    appel à Stripe ici : elle se contente d'afficher ce que la commande
    contient déjà en base, puisque c'est le webhook (ou la simulation) qui a
    la responsabilité d'activer réellement les accès."""
    commande = (
        session.query(Commande).filter_by(stripe_session_id=session_id).first()
        if session_id else None
    )
    return templates.TemplateResponse(
        request, "eleve/paiement_confirme.html",
        {"eleve": eleve, "commande": commande, "profil": _profil_pour_affichage(session)},
    )

@router.get("/portail", response_class=HTMLResponse)
def page_portail(request: Request, session: Session = Depends(obtenir_session)):
    return templates.TemplateResponse(request, "eleve/portail.html", {
        "profil": _profil_pour_affichage(session),
        "url_site_vitrine": URL_SITE_VITRINE,
    })

@router.get("/eleve/inscription", response_class=HTMLResponse)
def page_inscription(request: Request, session: Session = Depends(obtenir_session)):
    return templates.TemplateResponse(request, "eleve/inscription.html", {
        "profil": _profil_pour_affichage(session),
        "url_site_vitrine": URL_SITE_VITRINE,
    })

@router.get("/eleve/catalogue", response_class=HTMLResponse)
def page_catalogue(request: Request, session: Session = Depends(obtenir_session)):
    return templates.TemplateResponse(request, "eleve/catalogue.html", {
        "profil": _profil_pour_affichage(session),
        "url_site_vitrine": URL_SITE_VITRINE,
    })


@router.get("/reveil", response_class=HTMLResponse)
def page_reveil(request: Request, dest: str = "eleve"):
    destinations = {
        "eleve": "/eleve/connexion",
        "admin": "/admin/connexion",
    }
    url_dest = destinations.get(dest, "/eleve/connexion")
    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Chargement — Mon espace formation</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: Georgia, serif;
      background: #faf8f5;
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
      padding: 2rem;
      text-align: center;
    }}
    .card {{
      background: #fff;
      border-radius: 16px;
      padding: 3rem 2.5rem;
      max-width: 440px;
      width: 100%;
      box-shadow: 0 4px 32px rgba(0,0,0,0.07);
    }}
    .label {{
      font-size: 0.85rem;
      letter-spacing: 0.12em;
      color: #aaa;
      text-transform: uppercase;
      margin-bottom: 1.5rem;
    }}
    h1 {{
      font-size: 1.4rem;
      font-weight: normal;
      color: #2d2d2d;
      margin-bottom: 0.75rem;
    }}
    p {{
      font-size: 0.95rem;
      color: #777;
      line-height: 1.65;
      margin-bottom: 2rem;
    }}
    .dots {{
      display: flex;
      gap: 10px;
      justify-content: center;
      margin-bottom: 1.75rem;
    }}
    .dot {{
      width: 11px;
      height: 11px;
      border-radius: 50%;
      background: #c4a882;
      animation: pulse 1.4s ease-in-out infinite;
    }}
    .dot:nth-child(2) {{ animation-delay: 0.2s; }}
    .dot:nth-child(3) {{ animation-delay: 0.4s; }}
    @keyframes pulse {{
      0%, 80%, 100% {{ opacity: 0.25; transform: scale(0.8); }}
      40% {{ opacity: 1; transform: scale(1); }}
    }}
    .status {{
      font-size: 0.85rem;
      color: #bbb;
      min-height: 1.2em;
    }}
  </style>
</head>
<body>
  <div class="card">
    <div class="label">Laurence Mermet-Bijon · Formation</div>
    <h1>Préparation de votre espace…</h1>
    <p>Le serveur s'éveille, cela prend quelques secondes.<br>
       Vous serez redirigée automatiquement.</p>
    <div class="dots">
      <div class="dot"></div>
      <div class="dot"></div>
      <div class="dot"></div>
    </div>
    <div class="status" id="status">Connexion en cours…</div>
  </div>
  <script>
    var dest = "{url_dest}";
    var tries = 0;
    function ping() {{
      tries++;
      fetch("/ping", {{ cache: "no-store" }})
        .then(function(r) {{
          if (r.ok) {{
            document.getElementById("status").textContent = "\u2713 Prêt — redirection en cours…";
            setTimeout(function() {{ window.location.href = dest; }}, 500);
          }} else {{
            retry();
          }}
        }})
        .catch(function() {{ retry(); }});
    }}
    function retry() {{
      document.getElementById("status").textContent = "Démarrage… (" + tries + "s)";
      setTimeout(ping, 1000);
    }}
    setTimeout(ping, 800);
  </script>
</body>
</html>""";
    return HTMLResponse(content=html)
