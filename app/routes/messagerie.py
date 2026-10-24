"""
Messagerie élèves <-> Laurence : routes admin, élève, pages HTML et notifications.
Modèles : app/messagerie_models.py (nouvelles tables uniquement).

Admin  (/admin/messagerie/...) : liste des fils, annonces, envoi à un groupe
        (toutes les actives / selon l'avancement) ou à une personne, réponses.
Élève  (/api/eleve/formations/{id}/messages) : lire le fil (annonces + conversation
        privée), écrire à Laurence. Visible seulement si l'élève a accès à la
        formation ET si la messagerie est ouverte (réglage, sinon comptes test seuls).
E-mails : envoyés juste après un message si le destinataire n'a pas reçu d'e-mail de
        la messagerie depuis 1 h ; sinon regroupés par la tâche planifiée
        POST /cron/messagerie-notifications (GitHub Actions, toutes les heures en journée).
"""
import logging
from datetime import datetime, timedelta
from html import escape

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from typing import List, Optional

from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import URL_PLATEFORME, URL_SITE_VITRINE
from ..database import obtenir_session, SessionLocal
from ..models import Administrateur, Eleve, Formation, AccesFormation, ValidationChapitre, chapitre_dans_le_niveau
from ..messagerie_models import (
    Conversation, MessagePrive, Annonce, AnnonceDestinataire, PieceJointe,
    lire_parametre, ecrire_parametre, messagerie_visible_pour,
)
from .. import stockage_r2
from .auth import admin_connecte, eleve_connecte
from .. import emails

logger = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

TEXTE_MAX = 5000
DELAI_REGROUPEMENT = timedelta(hours=1)


# ---------------------------------------------------------------------------
# Outils communs
# ---------------------------------------------------------------------------

def _iso(dt):
    return dt.isoformat() + "Z" if dt else None


def _nom(eleve):
    return ("%s %s" % (eleve.prenom or "", eleve.nom or "")).strip() or eleve.email


def _nettoyer(texte: str, vide_permis: bool = False) -> str:
    texte = (texte or "").strip()
    if not texte and not vide_permis:
        raise HTTPException(status_code=400, detail="Le message est vide.")
    if len(texte) > TEXTE_MAX:
        raise HTTPException(status_code=400, detail="Message trop long (%d caractères maximum)." % TEXTE_MAX)
    return texte


def _acces_actifs(session: Session, formation_id: int) -> list:
    """Élèves qui ont accès à la formation et dont le compte est actif."""
    return (
        session.query(AccesFormation).join(Eleve)
        .filter(AccesFormation.formation_id == formation_id, Eleve.actif.is_(True))
        .all()
    )


def _avancements(session: Session, formation: Formation, acces_liste: list) -> dict:
    """eleve_id -> {pct, libelle, termines:set(module_id), commences:set(module_id)}.
    Une seule requête pour toutes les validations de la formation."""
    modules = list(formation.modules)
    chap_ids = [c.id for m in modules for c in m.chapitres]
    valides = {}
    if chap_ids and acces_liste:
        rows = (
            session.query(ValidationChapitre.eleve_id, ValidationChapitre.chapitre_id)
            .filter(ValidationChapitre.chapitre_id.in_(chap_ids),
                    ValidationChapitre.eleve_id.in_([a.eleve_id for a in acces_liste]))
            .all()
        )
        for e_id, c_id in rows:
            valides.setdefault(e_id, set()).add(c_id)
    res = {}
    for a in acces_liste:
        v = valides.get(a.eleve_id, set())
        total = fait = 0
        termines, commences, courant = set(), set(), None
        for i, m in enumerate(modules):
            visibles = [c for c in m.chapitres if chapitre_dans_le_niveau(formation, a.niveau, c)]
            if not visibles:
                continue
            n_ok = sum(1 for c in visibles if c.id in v)
            total += len(visibles)
            fait += n_ok
            if n_ok:
                commences.add(m.id)
            if n_ok == len(visibles):
                termines.add(m.id)
            elif courant is None:
                courant = "Module %d — %s" % (i + 1, m.titre)
        pct = round(100 * fait / total) if total else 0
        if fait == 0:
            libelle = "Pas encore commencé"
        elif courant is None:
            libelle = "Formation terminée"
        else:
            libelle = courant
        res[a.eleve_id] = {"pct": pct, "libelle": libelle, "termines": termines, "commences": commences}
    return res


def _conversation(session: Session, eleve_id: int, formation_id: int, creer: bool = False):
    conv = session.query(Conversation).filter_by(eleve_id=eleve_id, formation_id=formation_id).first()
    if conv is None and creer:
        conv = Conversation(eleve_id=eleve_id, formation_id=formation_id, dernier_message_le=datetime.utcnow())
        session.add(conv)
        session.flush()
    return conv


def _fil_eleve(session: Session, eleve_id: int, formation_id: int, conv) -> list:
    """Annonces reçues + messages privés, du plus ancien au plus récent."""
    items = []
    lignes = (
        session.query(AnnonceDestinataire, Annonce)
        .join(Annonce, Annonce.id == AnnonceDestinataire.annonce_id)
        .filter(AnnonceDestinataire.eleve_id == eleve_id, Annonce.formation_id == formation_id)
        .all()
    )
    for dest, ann in lignes:
        items.append({"type": "annonce", "id": ann.id, "auteur": "admin", "objet": ann.objet or "",
                      "texte": ann.texte, "date": _iso(ann.cree_le), "cible": ann.cible or "", "_t": ann.cree_le})
    if conv is not None:
        for m in conv.messages:
            items.append({"type": "message", "id": m.id, "auteur": m.auteur, "objet": "",
                          "texte": m.texte, "date": _iso(m.cree_le), "cible": "", "_t": m.cree_le})
    items.sort(key=lambda x: x["_t"] or datetime.min)
    _ajouter_pieces(session, items)
    for it in items:
        it.pop("_t", None)
    return items


# ---------------------------------------------------------------------------
# Pièces jointes (fichiers sur Cloudflare R2, jamais dans Neon)
# ---------------------------------------------------------------------------

PJ_MAX_ELEVE_MO = 50
PJ_MAX_ADMIN_MO = 1024
PJ_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".odt", ".txt", ".rtf", ".xls", ".xlsx", ".ppt", ".pptx",
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".heif",
    ".mp3", ".m4a", ".aac", ".wav", ".ogg", ".oga", ".opus", ".webm",
    ".mp4", ".m4v", ".mov",
}
PJ_MAX_PAR_MESSAGE = 10


def _piece_json(p: PieceJointe) -> dict:
    return {"id": p.id, "nom": p.nom, "type_mime": p.type_mime, "taille": p.taille, "vocal": bool(p.vocal),
            "url": "/messagerie/pieces/%d" % p.id}


def _ajouter_pieces(session: Session, items: list) -> None:
    """Ajoute à chaque élément du fil la liste de ses pièces jointes (une seule requête)."""
    ids_m = [it["id"] for it in items if it["type"] == "message"]
    ids_a = [it["id"] for it in items if it["type"] == "annonce"]
    par_m, par_a = {}, {}
    if ids_m or ids_a:
        q = session.query(PieceJointe)
        conds = []
        if ids_m:
            conds.append(PieceJointe.message_id.in_(ids_m))
        if ids_a:
            conds.append(PieceJointe.annonce_id.in_(ids_a))
        from sqlalchemy import or_
        for p in q.filter(or_(*conds)).order_by(PieceJointe.id).all():
            if p.message_id:
                par_m.setdefault(p.message_id, []).append(_piece_json(p))
            elif p.annonce_id:
                par_a.setdefault(p.annonce_id, []).append(_piece_json(p))
    for it in items:
        it["pieces"] = (par_m if it["type"] == "message" else par_a).get(it["id"], [])


def _preparer_piece(session: Session, nom: str, type_mime: str, taille: int, vocal: bool, auteur: str,
                    formation_id: Optional[int], eleve_id: Optional[int], max_mo: int) -> dict:
    if not stockage_r2.r2_actif():
        raise HTTPException(status_code=503, detail="L'envoi de fichiers n'est pas disponible pour le moment.")
    nom = (nom or "fichier").strip()[-200:]
    ext = ("." + nom.rsplit(".", 1)[-1].lower()) if "." in nom else ""
    if ext not in PJ_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Ce type de fichier n'est pas accepté (documents, photos, audios ou vidéos).")
    if taille <= 0 or taille > max_mo * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Fichier vide ou trop lourd (%d Mo maximum)." % max_mo)
    dossier = "messagerie/f%s/%s" % (formation_id or 0, ("e%d" % eleve_id) if eleve_id else "laurence")
    cle = stockage_r2.nouvelle_cle(dossier, nom)
    p = PieceJointe(cle=cle, nom=nom, type_mime=(type_mime or "application/octet-stream")[:120], taille=taille,
                    vocal=bool(vocal), auteur=auteur, eleve_id=eleve_id, formation_id=formation_id)
    session.add(p)
    session.commit()
    return {"id": p.id, "url": stockage_r2.url_depot(cle), "type_mime": p.type_mime}


def _rattacher_pieces(session: Session, ids, auteur: str, eleve_id: Optional[int], formation_id: Optional[int],
                      message_id: Optional[int] = None, annonce_id: Optional[int] = None) -> list:
    """Vérifie que les pièces appartiennent bien à l'auteur, ne sont pas déjà envoyées,
    et sont réellement arrivées sur R2 ; puis les rattache au message / à l'annonce."""
    ids = list(dict.fromkeys(ids or []))[:PJ_MAX_PAR_MESSAGE]
    pieces = []
    for pid in ids:
        p = session.get(PieceJointe, pid)
        if p is None or p.auteur != auteur or p.message_id or p.annonce_id:
            raise HTTPException(status_code=400, detail="Pièce jointe invalide.")
        if auteur == "eleve" and (p.eleve_id != eleve_id or p.formation_id != formation_id):
            raise HTTPException(status_code=400, detail="Pièce jointe invalide.")
        taille, _ = stockage_r2.infos_objet(p.cle)
        if not taille:
            raise HTTPException(status_code=400, detail="« %s » n'a pas fini d'être envoyé. Réessaie dans un instant." % p.nom)
        p.taille = taille
        pieces.append(p)
    for p in pieces:
        p.message_id, p.annonce_id = message_id, annonce_id
        if formation_id and not p.formation_id:
            p.formation_id = formation_id
    return pieces


def _texte_notification(texte: str, pieces) -> str:
    """Texte des e-mails : on signale les pièces jointes par leur nom."""
    lignes = [texte] if texte else []
    for p in pieces:
        lignes.append(("🎙️ Message vocal" if p.vocal else "📎 " + p.nom))
    return "\n".join(lignes)


# ---------------------------------------------------------------------------
# E-mails de notification
# ---------------------------------------------------------------------------

def _cadre_email(titre: str, sous_titre: str, corps: str, bouton_lien: str, bouton_texte: str, pied: str) -> str:
    return (
        '<div style="font-family:Georgia,serif;max-width:600px;margin:0 auto;background:#FDFAF5;'
        'border:1px solid #e8dfc8;border-radius:12px;overflow:hidden;">'
        '<div style="background:#2E2210;color:#F5EDD6;padding:22px 28px;">'
        '<div style="font-size:24px;font-style:italic;">%s</div>'
        '<div style="font-size:13px;color:#D9C08A;margin-top:4px;font-family:Arial,sans-serif;">%s</div></div>'
        '<div style="padding:24px 28px;color:#2E2210;">%s'
        '<p style="margin:24px 0 8px;"><a href="%s" style="background:#B8922A;color:#1E1608;text-decoration:none;'
        'border-radius:6px;padding:13px 22px;font-family:Arial,sans-serif;font-weight:bold;font-size:15px;'
        'display:inline-block;">%s</a></p>'
        '<p style="font-size:12px;color:#8a7d62;margin-top:22px;font-family:Arial,sans-serif;line-height:1.5;">%s</p>'
        '</div></div>'
    ) % (escape(titre), escape(sous_titre), corps, bouton_lien, escape(bouton_texte), pied)


def _bloc_message(qui: str, texte: str) -> str:
    extrait = texte if len(texte) <= 600 else texte[:600] + "…"
    return ('<p style="margin:16px 0 4px;font-family:Arial,sans-serif;font-size:13px;color:#6B5A3A;">%s</p>'
            '<div style="border-left:3px solid #B8922A;background:#fff;padding:12px 16px;font-size:17px;'
            'line-height:1.45;white-space:pre-wrap;">%s</div>') % (escape(qui), escape(extrait))


def _destinataire_admin() -> str:
    return emails.EMAIL_ADMIN


def notifier_admin(session: Session, forcer: bool = False) -> int:
    """Regroupe les messages d'élèves pas encore signalés en un seul e-mail à Laurence."""
    a_signaler = (
        session.query(MessagePrive).join(Conversation)
        .filter(MessagePrive.auteur == "eleve", MessagePrive.notifier.is_(True), MessagePrive.notifie_le.is_(None))
        .order_by(MessagePrive.cree_le).all()
    )
    if not a_signaler:
        return 0
    if not forcer:
        dernier = (session.query(func.max(MessagePrive.notifie_le))
                   .filter(MessagePrive.auteur == "eleve").scalar())
        if dernier and datetime.utcnow() - dernier < DELAI_REGROUPEMENT:
            return 0  # un e-mail est parti il y a moins d'une heure : la tâche planifiée regroupera
    blocs, noms = [], []
    for m in a_signaler:
        conv = m.conversation
        eleve = session.get(Eleve, conv.eleve_id)
        formation = session.get(Formation, conv.formation_id)
        if eleve is None or formation is None:
            continue
        noms.append(eleve.prenom or _nom(eleve))
        pjs = session.query(PieceJointe).filter_by(message_id=m.id).all()
        blocs.append(_bloc_message("%s · %s" % (_nom(eleve), formation.titre), _texte_notification(m.texte, pjs)))
    noms_uniques = list(dict.fromkeys(noms))
    if len(a_signaler) == 1:
        sujet = "%s t'a écrit — %s" % (noms_uniques[0], session.get(Formation, a_signaler[0].conversation.formation_id).titre)
    else:
        sujet = "%d nouveaux messages d'élèves (%s)" % (len(a_signaler), ", ".join(noms_uniques[:4]))
    corps = _cadre_email(
        "Nouveau message" if len(a_signaler) == 1 else "Nouveaux messages",
        "Messagerie de la plateforme", "".join(blocs),
        "%s/admin/page/messagerie" % URL_PLATEFORME.rstrip("/"), "Répondre sur la plateforme",
        "Ne réponds pas à cet e-mail : ta réponse doit être écrite sur la plateforme pour arriver à l'élève. "
        "Les messages reçus dans la même heure sont regroupés en un seul e-mail.")
    if emails._envoyer_email(_destinataire_admin(), sujet, corps):
        maintenant = datetime.utcnow()
        for m in a_signaler:
            m.notifie_le = maintenant
        session.commit()
        return len(a_signaler)
    return 0


def notifier_eleve(session: Session, eleve: Eleve, forcer: bool = False) -> int:
    """Un e-mail PAR FORMATION, regroupant annonces et messages privés non signalés.
    Le regroupement d'une heure se fait formation par formation : un message pour
    Rebirth n'empêche pas l'e-mail d'un message pour une autre formation."""
    msgs = (
        session.query(MessagePrive).join(Conversation)
        .filter(Conversation.eleve_id == eleve.id, MessagePrive.auteur == "admin",
                MessagePrive.notifier.is_(True), MessagePrive.notifie_le.is_(None))
        .order_by(MessagePrive.cree_le).all()
    )
    dests = (
        session.query(AnnonceDestinataire).join(Annonce)
        .filter(AnnonceDestinataire.eleve_id == eleve.id, AnnonceDestinataire.notifie_le.is_(None),
                Annonce.notifier.is_(True))
        .all()
    )
    if not msgs and not dests:
        return 0
    maintenant = datetime.utcnow()
    if not eleve.actif or not messagerie_visible_pour(session, eleve):
        # Messagerie pas encore ouverte à cette élève : on ne lui envoie rien, et on
        # marque comme traité pour ne pas lui envoyer d'arriéré le jour de l'ouverture.
        for x in msgs + dests:
            x.notifie_le = maintenant
        session.commit()
        return 0
    ids_acces = {a.formation_id for a in eleve.acces_formations}
    par_formation = {}  # formation_id -> [(date, html, objet_a_marquer)]
    for m in msgs:
        par_formation.setdefault(m.conversation.formation_id, []).append(
            (m.cree_le, _bloc_message("Message de Laurence", _texte_notification(
                m.texte, session.query(PieceJointe).filter_by(message_id=m.id).all())), m))
    for d in dests:
        ann = d.annonce
        titre = "Message de Laurence au groupe" + (" — " + ann.objet if ann.objet else "")
        texte_ann = _texte_notification(ann.texte, session.query(PieceJointe).filter_by(annonce_id=ann.id).all())
        par_formation.setdefault(ann.formation_id, []).append((ann.cree_le, _bloc_message(titre, texte_ann), d))
    nb = 0
    for f_id, elements in par_formation.items():
        a_marquer = [e[2] for e in elements]
        if f_id not in ids_acces:
            # Plus d'accès à cette formation : rien à envoyer.
            for x in a_marquer:
                x.notifie_le = maintenant
            session.commit()
            continue
        if not forcer:
            d1 = (session.query(func.max(MessagePrive.notifie_le)).join(Conversation)
                  .filter(Conversation.eleve_id == eleve.id, Conversation.formation_id == f_id,
                          MessagePrive.auteur == "admin").scalar())
            d2 = (session.query(func.max(AnnonceDestinataire.notifie_le)).join(Annonce)
                  .filter(AnnonceDestinataire.eleve_id == eleve.id, Annonce.formation_id == f_id).scalar())
            dates = [d for d in (d1, d2) if d]
            if dates and maintenant - max(dates) < DELAI_REGROUPEMENT:
                continue  # e-mail déjà parti pour cette formation il y a moins d'1 h : regroupé plus tard
        elements.sort(key=lambda e: e[0])
        f_titre = session.get(Formation, f_id).titre
        lien = "%s/eleve/voir-formation/%d/messages" % (URL_PLATEFORME.rstrip("/"), f_id)
        sujet = ("Laurence t'a écrit — %s" % f_titre) if len(elements) == 1 else \
            ("%d nouveaux messages de Laurence — %s" % (len(elements), f_titre))
        corps = _cadre_email(
            "Bonjour %s," % (eleve.prenom or ""), "Messagerie — %s" % f_titre,
            "".join(e[1] for e in elements), lien, "Lire et répondre",
            "Pour répondre, utilise le bouton ci-dessus : ta réponse arrive directement à Laurence, "
            "et elle seule la lit. Ne réponds pas à cet e-mail. Si plusieurs messages arrivent "
            "dans la même heure, ils sont regroupés en un seul e-mail.")
        if emails._envoyer_email(eleve.email, sujet, corps):
            for x in a_marquer:
                x.notifie_le = maintenant
            session.commit()
            nb += len(elements)
    return nb


def _notifier_en_arriere_plan(eleve_ids=None, admin=False):
    """Lancé après la réponse HTTP : n'envoie que si aucun e-mail n'est parti depuis 1 h."""
    session = SessionLocal()
    try:
        if admin:
            notifier_admin(session)
        for e_id in eleve_ids or []:
            eleve = session.get(Eleve, e_id)
            if eleve:
                notifier_eleve(session, eleve)
    except Exception as e:
        logger.error("Notification messagerie : %s", e)
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Pages HTML
# ---------------------------------------------------------------------------

@router.get("/admin/page/messagerie", response_class=HTMLResponse)
def page_messagerie_admin(request: Request, admin: Administrateur = Depends(admin_connecte)):
    return templates.TemplateResponse(request, "admin/messagerie.html", {
        "profil": {"nom": admin.nom, "prenom": admin.prenom}, "page_active": "messagerie",
        "url_site_vitrine": URL_SITE_VITRINE,
    })


@router.get("/eleve/voir-formation/{formation_id}/messages", response_class=HTMLResponse)
def page_messages_eleve(request: Request, formation_id: int, eleve: Eleve = Depends(eleve_connecte),
                        session: Session = Depends(obtenir_session)):
    formation = _verifier_acces_eleve(session, eleve, formation_id)
    from ..pages import _profil_pour_affichage
    return templates.TemplateResponse(request, "eleve/messages.html", {
        "eleve": eleve, "formation": formation, "profil": _profil_pour_affichage(session),
        "url_site_vitrine": URL_SITE_VITRINE, "onglet_actif": "messages",
        "messagerie_visible": True, "nb_messages_non_lus": 0,
    })


def infos_onglets_eleve(session: Session, eleve: Eleve, formation_id: int) -> dict:
    """Pour la page Contenu : l'onglet Messages apparaît-il, et combien de non-lus ?
    Ne lève jamais d'erreur (la page Contenu doit toujours s'afficher)."""
    try:
        if not messagerie_visible_pour(session, eleve):
            return {"messagerie_visible": False, "nb_messages_non_lus": 0}
        return {"messagerie_visible": True, "nb_messages_non_lus": _non_lus_eleve(session, eleve.id, formation_id)}
    except Exception as e:
        session.rollback()
        logger.error("Onglets messagerie : %s", e)
        return {"messagerie_visible": False, "nb_messages_non_lus": 0}


def _non_lus_eleve(session: Session, eleve_id: int, formation_id: int) -> int:
    n = (session.query(AnnonceDestinataire).join(Annonce)
         .filter(AnnonceDestinataire.eleve_id == eleve_id, Annonce.formation_id == formation_id,
                 AnnonceDestinataire.lu_le.is_(None)).count())
    conv = _conversation(session, eleve_id, formation_id)
    if conv is not None and conv.non_lu_eleve:
        n += 1
    return n


# ---------------------------------------------------------------------------
# API élève
# ---------------------------------------------------------------------------

def _verifier_acces_eleve(session: Session, eleve: Eleve, formation_id: int) -> Formation:
    formation = session.get(Formation, formation_id)
    if formation is None:
        raise HTTPException(status_code=404, detail="Formation introuvable.")
    acces = session.query(AccesFormation).filter_by(eleve_id=eleve.id, formation_id=formation_id).first()
    if acces is None:
        raise HTTPException(status_code=403, detail="Tu n'as pas accès à cette formation.")
    if not formation.actif and not eleve.compte_test:
        raise HTTPException(status_code=403, detail="Cette formation n'est actuellement pas disponible.")
    if not messagerie_visible_pour(session, eleve):
        raise HTTPException(status_code=404, detail="Messagerie indisponible.")
    return formation


class TexteMessage(BaseModel):
    texte: str = ""
    pieces: Optional[List[int]] = None


class DemandePiece(BaseModel):
    nom_fichier: str
    type_mime: str = ""
    taille: int
    vocal: bool = False
    formation_id: Optional[int] = None   # côté admin : formation concernée (rangement)


@router.post("/api/eleve/formations/{formation_id}/pieces/preparer")
def preparer_piece_eleve(formation_id: int, d: DemandePiece, eleve: Eleve = Depends(eleve_connecte),
                         session: Session = Depends(obtenir_session)):
    _verifier_acces_eleve(session, eleve, formation_id)
    return _preparer_piece(session, d.nom_fichier, d.type_mime, d.taille, d.vocal, "eleve",
                           formation_id, eleve.id, PJ_MAX_ELEVE_MO)


@router.get("/messagerie/pieces/{piece_id}")
def ouvrir_piece(piece_id: int, request: Request, telecharger: int = 0, session: Session = Depends(obtenir_session)):
    """Vérifie les droits puis redirige vers un lien R2 temporaire."""
    p = session.get(PieceJointe, piece_id)
    if p is None:
        raise HTTPException(status_code=404, detail="Fichier introuvable.")
    admin_id = request.session.get("admin_id")
    est_admin = admin_id is not None and session.get(Administrateur, admin_id) is not None
    if not est_admin:
        eleve_id = request.session.get("eleve_id")
        eleve = session.get(Eleve, eleve_id) if eleve_id else None
        if eleve is None or not eleve.actif:
            raise HTTPException(status_code=401, detail="Connexion requise.")
        autorise = False
        formation_id = None
        if p.message_id:
            m = session.get(MessagePrive, p.message_id)
            if m is not None and m.conversation.eleve_id == eleve.id:
                autorise, formation_id = True, m.conversation.formation_id
        elif p.annonce_id:
            d = session.query(AnnonceDestinataire).filter_by(annonce_id=p.annonce_id, eleve_id=eleve.id).first()
            if d is not None:
                autorise, formation_id = True, d.annonce.formation_id
        elif p.auteur == "eleve" and p.eleve_id == eleve.id:
            autorise, formation_id = True, p.formation_id   # sa propre pièce, pas encore envoyée (aperçu)
        if not autorise:
            raise HTTPException(status_code=404, detail="Fichier introuvable.")
        _verifier_acces_eleve(session, eleve, formation_id)   # plus d'accès à la formation = plus de fichiers
    if not stockage_r2.r2_actif():
        raise HTTPException(status_code=503, detail="Stockage indisponible.")
    url = stockage_r2.url_signee(stockage_r2.PREFIXE + p.cle, p.nom if telecharger else None)
    return Response(status_code=307, headers={"Location": url, "Cache-Control": "private, no-store"})


@router.get("/api/eleve/formations/{formation_id}/messages")
def lire_messages_eleve(formation_id: int, eleve: Eleve = Depends(eleve_connecte),
                        session: Session = Depends(obtenir_session)):
    formation = _verifier_acces_eleve(session, eleve, formation_id)
    conv = _conversation(session, eleve.id, formation_id)
    items = _fil_eleve(session, eleve.id, formation_id, conv)
    maintenant = datetime.utcnow()
    (session.query(AnnonceDestinataire)
     .filter(AnnonceDestinataire.eleve_id == eleve.id, AnnonceDestinataire.lu_le.is_(None),
             AnnonceDestinataire.annonce_id.in_(
                 session.query(Annonce.id).filter(Annonce.formation_id == formation_id)))
     .update({AnnonceDestinataire.lu_le: maintenant}, synchronize_session=False))
    if conv is not None and conv.non_lu_eleve:
        conv.non_lu_eleve = False
    session.commit()
    return {"formation": {"id": formation.id, "titre": formation.titre}, "items": items}


@router.post("/api/eleve/formations/{formation_id}/messages")
def ecrire_message_eleve(formation_id: int, corps: TexteMessage, taches: BackgroundTasks,
                         eleve: Eleve = Depends(eleve_connecte), session: Session = Depends(obtenir_session)):
    _verifier_acces_eleve(session, eleve, formation_id)
    texte = _nettoyer(corps.texte, vide_permis=bool(corps.pieces))
    conv = _conversation(session, eleve.id, formation_id, creer=True)
    m = MessagePrive(conversation_id=conv.id, auteur="eleve", texte=texte, notifier=True)
    session.add(m)
    session.flush()
    pieces = _rattacher_pieces(session, corps.pieces, "eleve", eleve.id, formation_id, message_id=m.id)
    conv.dernier_message_le = datetime.utcnow()
    conv.non_lu_admin = True
    session.commit()
    taches.add_task(_notifier_en_arriere_plan, admin=True)
    return {"ok": True, "message": {"type": "message", "id": m.id, "auteur": "eleve", "objet": "",
                                    "texte": m.texte, "date": _iso(m.cree_le), "cible": "",
                                    "pieces": [_piece_json(p) for p in pieces]}}


# ---------------------------------------------------------------------------
# API admin
# ---------------------------------------------------------------------------

admin_router = APIRouter(prefix="/admin/messagerie", dependencies=[Depends(admin_connecte)])


@admin_router.get("/non-lus")
def admin_non_lus(session: Session = Depends(obtenir_session)):
    return {"nb": session.query(Conversation).filter(Conversation.non_lu_admin.is_(True)).count()}


@admin_router.post("/pieces/preparer")
def admin_preparer_piece(d: DemandePiece, session: Session = Depends(obtenir_session)):
    return _preparer_piece(session, d.nom_fichier, d.type_mime, d.taille, d.vocal, "admin",
                           d.formation_id, None, PJ_MAX_ADMIN_MO)


@admin_router.get("/documents")
def admin_documents_recus(session: Session = Depends(obtenir_session)):
    """Toutes les pièces envoyées par les élèves (les plus récentes d'abord)."""
    res = []
    lignes = (session.query(PieceJointe, MessagePrive, Conversation)
              .join(MessagePrive, MessagePrive.id == PieceJointe.message_id)
              .join(Conversation, Conversation.id == MessagePrive.conversation_id)
              .filter(PieceJointe.auteur == "eleve")
              .order_by(PieceJointe.cree_le.desc()).limit(300).all())
    for p, m, c in lignes:
        eleve = session.get(Eleve, c.eleve_id)
        formation = session.get(Formation, c.formation_id)
        res.append(dict(_piece_json(p), eleve=_nom(eleve) if eleve else "?",
                        formation=formation.titre if formation else "?",
                        conversation_id=c.id, date=_iso(m.cree_le)))
    return res


@admin_router.get("/reglages")
def admin_lire_reglages(session: Session = Depends(obtenir_session)):
    return {"visible_eleves": lire_parametre(session, "messagerie_visible_eleves", "tous")}


class Reglages(BaseModel):
    visible_eleves: str


@admin_router.post("/reglages")
def admin_ecrire_reglages(corps: Reglages, session: Session = Depends(obtenir_session)):
    if corps.visible_eleves not in ("test", "tous"):
        raise HTTPException(status_code=400, detail="Valeur inconnue.")
    ecrire_parametre(session, "messagerie_visible_eleves", corps.visible_eleves)
    return {"visible_eleves": corps.visible_eleves}


@admin_router.get("/formations")
def admin_formations(session: Session = Depends(obtenir_session)):
    """Formations (actives d'abord) avec leurs modules numérotés, pour les listes de choix."""
    res = []
    for f in session.query(Formation).order_by(Formation.actif.desc(), Formation.ordre_affichage, Formation.id).all():
        res.append({
            "id": f.id, "titre": f.titre, "actif": bool(f.actif),
            "modules": [{"id": m.id, "libelle": "Module %d — %s" % (i + 1, m.titre)} for i, m in enumerate(f.modules)],
        })
    return res


@admin_router.get("/destinataires")
def admin_tous_destinataires(session: Session = Depends(obtenir_session)):
    """Tout ce qu'il faut pour le formulaire « Nouveau message », en UN appel :
    formations, modules, élèves actives et leur avancement (modules terminés /
    commencés). Le navigateur calcule ensuite l'aperçu instantanément ; l'envoi
    refait le calcul côté serveur (c'est lui qui fait foi)."""
    res = []
    for f in session.query(Formation).order_by(Formation.actif.desc(), Formation.ordre_affichage, Formation.id).all():
        acces = _acces_actifs(session, f.id)
        av = _avancements(session, f, acces)
        eleves = []
        for a in acces:
            e = a.eleve
            v = av[e.id]
            eleves.append({"id": e.id, "nom": _nom(e), "email": e.email, "test": bool(e.compte_test),
                           "pct": v["pct"], "avancement": v["libelle"],
                           "termines": sorted(v["termines"]), "commences": sorted(v["commences"])})
        eleves.sort(key=lambda x: x["nom"].lower())
        res.append({"id": f.id, "titre": f.titre, "actif": bool(f.actif),
                    "modules": [{"id": m.id, "libelle": "Module %d — %s" % (i + 1, m.titre)} for i, m in enumerate(f.modules)],
                    "eleves": eleves})
    return {"visible_eleves": lire_parametre(session, "messagerie_visible_eleves", "tous"), "formations": res}


@admin_router.get("/formations/{formation_id}/eleves")
def admin_eleves_formation(formation_id: int, session: Session = Depends(obtenir_session)):
    formation = session.get(Formation, formation_id)
    if formation is None:
        raise HTTPException(status_code=404, detail="Formation introuvable.")
    acces = _acces_actifs(session, formation_id)
    av = _avancements(session, formation, acces)
    res = []
    for a in acces:
        e = a.eleve
        res.append({"id": e.id, "nom": _nom(e), "email": e.email, "test": bool(e.compte_test),
                    "pct": av[e.id]["pct"], "avancement": av[e.id]["libelle"]})
    res.sort(key=lambda x: x["nom"].lower())
    return res


class Cible(BaseModel):
    formation_id: int
    mode: str                                   # "toutes" | "avancement" | "une"
    module_termine_id: Optional[int] = None
    module_non_commence_id: Optional[int] = None
    eleve_id: Optional[int] = None
    eleve_ids: Optional[List[int]] = None       # mode "plusieurs"


def _resoudre_cible(session: Session, c: Cible):
    formation = session.get(Formation, c.formation_id)
    if formation is None:
        raise HTTPException(status_code=404, detail="Formation introuvable.")
    acces = _acces_actifs(session, formation.id)
    if c.mode == "une":
        acces = [a for a in acces if a.eleve_id == c.eleve_id]
        description = None
    elif c.mode == "plusieurs":
        choisis = set(c.eleve_ids or [])
        if not choisis:
            raise HTTPException(status_code=400, detail="Coche au moins une personne.")
        acces = [a for a in acces if a.eleve_id in choisis]
        description = "Sélection de %d personne%s" % (len(acces), "s" if len(acces) > 1 else "")
    elif c.mode == "avancement":
        if not c.module_termine_id and not c.module_non_commence_id:
            raise HTTPException(status_code=400, detail="Choisis au moins un critère d'avancement.")
        av = _avancements(session, formation, acces)
        libelles = {m.id: "module %d" % (i + 1) for i, m in enumerate(formation.modules)}
        if c.module_termine_id:
            acces = [a for a in acces if c.module_termine_id in av[a.eleve_id]["termines"]]
        if c.module_non_commence_id:
            acces = [a for a in acces if c.module_non_commence_id not in av[a.eleve_id]["commences"]]
        morceaux = []
        if c.module_termine_id:
            morceaux.append("%s terminé" % libelles.get(c.module_termine_id, "module"))
        if c.module_non_commence_id:
            morceaux.append("%s pas commencé" % libelles.get(c.module_non_commence_id, "module"))
        description = "Selon l'avancement : " + ", ".join(morceaux)
    elif c.mode == "toutes":
        description = "Toutes les élèves actives"
    else:
        raise HTTPException(status_code=400, detail="Mode inconnu.")
    return formation, acces, description


@admin_router.post("/apercu-destinataires")
def admin_apercu(c: Cible, session: Session = Depends(obtenir_session)):
    formation, acces, _ = _resoudre_cible(session, c)
    av = _avancements(session, formation, acces)
    visibles = lire_parametre(session, "messagerie_visible_eleves", "tous") == "tous"
    return {"nb": len(acces), "mode_test": not visibles, "eleves": sorted([
        {"id": a.eleve_id, "nom": _nom(a.eleve), "test": bool(a.eleve.compte_test),
         "avancement": av[a.eleve_id]["libelle"], "pct": av[a.eleve_id]["pct"]} for a in acces
    ], key=lambda x: x["nom"].lower())}


class Envoi(Cible):
    objet: str = ""
    texte: str = ""
    notifier: bool = True
    pieces: Optional[List[int]] = None


@admin_router.post("/envoyer")
def admin_envoyer(e: Envoi, taches: BackgroundTasks, session: Session = Depends(obtenir_session)):
    texte = _nettoyer(e.texte, vide_permis=bool(e.pieces))
    formation, acces, description = _resoudre_cible(session, e)
    if not acces:
        raise HTTPException(status_code=400, detail="Aucune élève ne correspond à ce choix.")
    maintenant = datetime.utcnow()
    if e.mode == "une":
        conv = _conversation(session, acces[0].eleve_id, formation.id, creer=True)
        if e.objet.strip():
            texte = e.objet.strip() + "\n\n" + texte
        m = MessagePrive(conversation_id=conv.id, auteur="admin", texte=texte, notifier=e.notifier)
        session.add(m)
        session.flush()
        _rattacher_pieces(session, e.pieces, "admin", None, formation.id, message_id=m.id)
        conv.dernier_message_le = maintenant
        conv.non_lu_eleve = True
        session.commit()
        if e.notifier:
            taches.add_task(_notifier_en_arriere_plan, eleve_ids=[acces[0].eleve_id])
        return {"ok": True, "type": "message", "nb": 1, "conversation_id": conv.id}
    ann = Annonce(formation_id=formation.id, objet=e.objet.strip()[:200] or None, texte=texte,
                  cible=description, notifier=e.notifier, cree_le=maintenant)
    session.add(ann)
    session.flush()
    _rattacher_pieces(session, e.pieces, "admin", None, formation.id, annonce_id=ann.id)
    for a in acces:
        session.add(AnnonceDestinataire(annonce_id=ann.id, eleve_id=a.eleve_id))
    session.commit()
    if e.notifier:
        taches.add_task(_notifier_en_arriere_plan, eleve_ids=[a.eleve_id for a in acces])
    return {"ok": True, "type": "annonce", "nb": len(acces), "annonce_id": ann.id}


@admin_router.get("/fils")
def admin_fils(filtre: str = "tous", session: Session = Depends(obtenir_session)):
    q = session.query(Conversation)
    if filtre == "nonlus":
        q = q.filter(Conversation.non_lu_admin.is_(True))
    convs = q.order_by(Conversation.dernier_message_le.desc()).limit(200).all()
    par_formation = {}
    for c in convs:
        par_formation.setdefault(c.formation_id, []).append(c)
    avs = {}
    for f_id, cs in par_formation.items():
        formation = session.get(Formation, f_id)
        acces = session.query(AccesFormation).filter(
            AccesFormation.formation_id == f_id,
            AccesFormation.eleve_id.in_([c.eleve_id for c in cs])).all()
        for e_id, v in _avancements(session, formation, acces).items():
            avs[(e_id, f_id)] = v["libelle"]
    res = []
    for c in convs:
        eleve = session.get(Eleve, c.eleve_id)
        formation = session.get(Formation, c.formation_id)
        dernier = c.messages[-1] if c.messages else None
        extrait = ""
        if dernier is not None:
            extrait = ("Toi : " if dernier.auteur == "admin" else "") + (
                dernier.texte.replace("\n", " ")[:140] or "📎 Pièce jointe")
        res.append({"id": c.id, "eleve_id": c.eleve_id, "eleve": _nom(eleve), "formation_id": c.formation_id,
                    "formation": formation.titre, "avancement": avs.get((c.eleve_id, c.formation_id), "Accès terminé"),
                    "extrait": extrait, "date": _iso(c.dernier_message_le), "non_lu": bool(c.non_lu_admin)})
    return res


@admin_router.get("/fils/{conversation_id}")
def admin_lire_fil(conversation_id: int, session: Session = Depends(obtenir_session)):
    conv = session.get(Conversation, conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation introuvable.")
    eleve = session.get(Eleve, conv.eleve_id)
    formation = session.get(Formation, conv.formation_id)
    acces = session.query(AccesFormation).filter_by(eleve_id=eleve.id, formation_id=formation.id).first()
    avancement = _avancements(session, formation, [acces])[eleve.id]["libelle"] if acces else "Accès terminé"
    items = _fil_eleve(session, eleve.id, formation.id, conv)
    if conv.non_lu_admin:
        conv.non_lu_admin = False
        session.commit()
    return {"id": conv.id, "eleve_id": eleve.id, "eleve": _nom(eleve), "prenom": eleve.prenom or "",
            "formation_id": formation.id, "formation": formation.titre, "avancement": avancement,
            "acces_actif": acces is not None and bool(eleve.actif), "items": items}


@admin_router.post("/fils/{conversation_id}/repondre")
def admin_repondre(conversation_id: int, corps: TexteMessage, taches: BackgroundTasks,
                   session: Session = Depends(obtenir_session)):
    conv = session.get(Conversation, conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation introuvable.")
    texte = _nettoyer(corps.texte, vide_permis=bool(corps.pieces))
    m = MessagePrive(conversation_id=conv.id, auteur="admin", texte=texte, notifier=True)
    session.add(m)
    session.flush()
    pieces = _rattacher_pieces(session, corps.pieces, "admin", None, conv.formation_id, message_id=m.id)
    conv.dernier_message_le = datetime.utcnow()
    conv.non_lu_eleve = True
    conv.non_lu_admin = False
    session.commit()
    taches.add_task(_notifier_en_arriere_plan, eleve_ids=[conv.eleve_id])
    return {"ok": True, "message": {"type": "message", "id": m.id, "auteur": "admin", "objet": "",
                                    "texte": m.texte, "date": _iso(m.cree_le), "cible": "",
                                    "pieces": [_piece_json(p) for p in pieces]}}


@admin_router.get("/eleves/{eleve_id}/formations")
def admin_formations_de_l_eleve(eleve_id: int, session: Session = Depends(obtenir_session)):
    """Formations auxquelles une élève a accès (pour « Écrire à cette élève »)."""
    return [a.formation_id for a in session.query(AccesFormation).filter_by(eleve_id=eleve_id).all()]


@admin_router.get("/conversation")
def admin_conversation_pour(eleve_id: int, formation_id: int, session: Session = Depends(obtenir_session)):
    """Id de la conversation d'une élève pour une formation (null si aucun échange)."""
    conv = _conversation(session, eleve_id, formation_id)
    return {"conversation_id": conv.id if conv else None}


@admin_router.get("/annonces")
def admin_annonces(session: Session = Depends(obtenir_session)):
    res = []
    for ann in session.query(Annonce).order_by(Annonce.cree_le.desc()).limit(100).all():
        formation = session.get(Formation, ann.formation_id)
        nb = len(ann.destinataires)
        lus = sum(1 for d in ann.destinataires if d.lu_le)
        res.append({"id": ann.id, "formation": formation.titre if formation else "?", "objet": ann.objet or "",
                    "extrait": ann.texte.replace("\n", " ")[:140], "date": _iso(ann.cree_le),
                    "cible": ann.cible or "", "nb": nb, "lus": lus})
    return res


@admin_router.get("/annonces/{annonce_id}")
def admin_annonce(annonce_id: int, session: Session = Depends(obtenir_session)):
    ann = session.get(Annonce, annonce_id)
    if ann is None:
        raise HTTPException(status_code=404, detail="Annonce introuvable.")
    formation = session.get(Formation, ann.formation_id)
    dests = []
    for d in ann.destinataires:
        e = session.get(Eleve, d.eleve_id)
        if e:
            conv = _conversation(session, e.id, ann.formation_id)
            dests.append({"eleve_id": e.id, "nom": _nom(e), "lu": d.lu_le is not None,
                          "conversation_id": conv.id if conv else None})
    dests.sort(key=lambda x: x["nom"].lower())
    return {"id": ann.id, "formation": formation.titre if formation else "?", "formation_id": ann.formation_id,
            "objet": ann.objet or "", "texte": ann.texte, "date": _iso(ann.cree_le), "cible": ann.cible or "",
            "destinataires": dests,
            "pieces": [_piece_json(p) for p in session.query(PieceJointe).filter_by(annonce_id=ann.id).all()]}


# ---------------------------------------------------------------------------
# Tâche planifiée : regroupement des notifications
# ---------------------------------------------------------------------------

@router.post("/cron/messagerie-notifications")
def cron_notifications(x_cron_token: str = Header(""), session: Session = Depends(obtenir_session)):
    from .rapport_hebdo import _verifier_jeton
    _verifier_jeton(x_cron_token)
    nb_admin = notifier_admin(session, forcer=True)
    ids = set(e_id for (e_id,) in session.query(Conversation.eleve_id).join(MessagePrive)
              .filter(MessagePrive.auteur == "admin", MessagePrive.notifier.is_(True),
                      MessagePrive.notifie_le.is_(None)).distinct().all())
    ids |= set(e_id for (e_id,) in session.query(AnnonceDestinataire.eleve_id).join(Annonce)
               .filter(AnnonceDestinataire.notifie_le.is_(None), Annonce.notifier.is_(True)).distinct().all())
    nb_eleves = 0
    for e_id in ids:
        eleve = session.get(Eleve, e_id)
        if eleve and notifier_eleve(session, eleve, forcer=True):
            nb_eleves += 1
    return {"ok": True, "messages_signales_admin": nb_admin, "eleves_prevenues": nb_eleves}
