"""
Page web TEMPORAIRE pour créer le premier compte administrateur, sans avoir
besoin d'un accès Shell (non disponible sur le plan gratuit de Render).

Protégée par une clé secrète dans l'URL elle-même (pas une vraie sécurité
de mot de passe, mais suffisante pour cet usage ponctuel et unique -- la
route refuse de toute façon de créer un second compte une fois le premier
en place, donc le risque réel est nul après la première utilisation).

Ce fichier peut être supprimé une fois le premier compte créé, mais ce n'est
pas obligatoire : il devient inoffensif dès qu'un administrateur existe déjà.
"""
from fastapi import APIRouter, Form, HTTPException
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from .database import SessionLocal
from .models import Administrateur

router = APIRouter()

CLE_SECRETE_SETUP = "laurence-setup-2026"  # juste un mot de passe simple temporaire pour cette page


@router.get("/setup-premier-admin/{cle}", response_class=HTMLResponse)
def page_setup_admin(cle: str):
    if cle != CLE_SECRETE_SETUP:
        raise HTTPException(status_code=404, detail="Page introuvable.")

    session = SessionLocal()
    nb_admins = session.query(Administrateur).count()
    session.close()

    if nb_admins > 0:
        return """
        <div style="font-family:sans-serif; max-width:480px; margin:60px auto; text-align:center;">
            <h2>Un compte administrateur existe déjà</h2>
            <p>Cette page ne sert qu'à créer le premier compte. Va sur
            <a href="/admin/connexion">/admin/connexion</a> pour te connecter.</p>
        </div>
        """

    return """
    <!DOCTYPE html>
    <html lang="fr">
    <head><meta charset="UTF-8"><title>Créer le compte administrateur</title>
    <style>
      body { font-family: sans-serif; max-width: 420px; margin: 60px auto; padding: 0 20px; }
      label { display: block; margin: 14px 0 4px; font-weight: 600; font-size: 14px; }
      input { width: 100%; padding: 8px 10px; border: 1px solid #ccc; border-radius: 6px; font-size: 14px; box-sizing: border-box; }
      button { margin-top: 20px; padding: 10px 20px; background: #2E2210; color: white; border: none; border-radius: 6px; cursor: pointer; font-size: 14px; }
      .erreur { color: #B3503D; margin-top: 10px; }
    </style>
    </head>
    <body>
      <h2>Créer ton compte administrateur</h2>
      <div id="erreur"></div>
      <form id="form-setup">
        <label>Prénom</label><input type="text" id="prenom" required>
        <label>Nom</label><input type="text" id="nom" required>
        <label>E-mail</label><input type="email" id="email" required>
        <label>Mot de passe (8 caractères minimum)</label><input type="password" id="mot_de_passe" required minlength="8">
        <button type="submit">Créer mon compte</button>
      </form>
      <script>
        document.getElementById('form-setup').addEventListener('submit', async function(e) {
          e.preventDefault();
          const data = new FormData();
          data.append('prenom', document.getElementById('prenom').value);
          data.append('nom', document.getElementById('nom').value);
          data.append('email', document.getElementById('email').value);
          data.append('mot_de_passe', document.getElementById('mot_de_passe').value);
          const resp = await fetch(window.location.pathname, { method: 'POST', body: data });
          if (resp.ok) {
            window.location.href = '/admin/connexion';
          } else {
            const err = await resp.json();
            document.getElementById('erreur').innerHTML = '<p class="erreur">' + (err.detail || 'Erreur') + '</p>';
          }
        });
      </script>
    </body>
    </html>
    """


@router.post("/setup-premier-admin/{cle}")
def creer_admin_via_web(
    cle: str, prenom: str = Form(...), nom: str = Form(...),
    email: str = Form(...), mot_de_passe: str = Form(...),
):
    if cle != CLE_SECRETE_SETUP:
        raise HTTPException(status_code=404, detail="Page introuvable.")

    session = SessionLocal()
    try:
        if session.query(Administrateur).count() > 0:
            raise HTTPException(status_code=400, detail="Un administrateur existe déjà.")
        if len(mot_de_passe) < 8:
            raise HTTPException(status_code=400, detail="Le mot de passe doit faire au moins 8 caractères.")

        admin = Administrateur(nom=nom.strip(), prenom=prenom.strip(), email=email.strip().lower())
        admin.definir_mot_de_passe(mot_de_passe)
        session.add(admin)
        session.commit()
        return {"ok": True}
    finally:
        session.close()
