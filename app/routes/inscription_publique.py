"""
Auto-inscription publique -- différent de la création d'élève par l'admin
(qui reste inchangée, avec son mailto contrôlé). Ici, un visiteur crée
lui-même son compte pour accéder au catalogue et acheter une formation.

À placer dans app/routes/inscription_publique.py
"""
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Request, Form, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from fastapi import Depends

from ..database import obtenir_session
from ..models import Eleve
from ..emails import email_bienvenue_inscription, email_nouvelle_inscription_admin

router = APIRouter()


@router.post("/eleve/inscription")
def creer_compte_eleve(
    request: Request,
    background_tasks: BackgroundTasks,
    prenom: str = Form(...),
    nom: str = Form(...),
    email: str = Form(...),
    mot_de_passe: str = Form(...),
    session: Session = Depends(obtenir_session),
):
    email_normalise = email.strip().lower()
    existe_deja = session.query(Eleve).filter_by(email=email_normalise).first()
    if existe_deja is not None:
        raise HTTPException(status_code=400, detail="Un compte existe déjà avec cette adresse e-mail.")

    if len(mot_de_passe) < 8:
        raise HTTPException(status_code=400, detail="Le mot de passe doit contenir au moins 8 caractères.")

    eleve = Eleve(prenom=prenom.strip(), nom=nom.strip(), email=email_normalise, actif=True)
    eleve.definir_mot_de_passe(mot_de_passe)
    session.add(eleve)
    session.commit()
    session.refresh(eleve)

    # Elle est connectee des l'inscription : on le compte comme sa premiere connexion
    # (evite aussi un doublon "nouvel eleve connecte" plus tard).
    eleve.nb_connexions = 1
    eleve.derniere_connexion = datetime.utcnow()
    session.commit()

    # E-mails envoyes en arriere-plan pour ne pas ralentir la page :
    # alerte pour Laurence + e-mail de bienvenue pour la cliente.
    background_tasks.add_task(email_nouvelle_inscription_admin, eleve.prenom, eleve.nom, eleve.email)
    background_tasks.add_task(email_bienvenue_inscription, eleve.prenom, eleve.email)

    # Connexion immédiate après inscription -- pas besoin de se reconnecter
    # juste après avoir créé son compte.
    request.session["eleve_id"] = eleve.id

    return RedirectResponse(url="/eleve/catalogue?bienvenue=1", status_code=303)
