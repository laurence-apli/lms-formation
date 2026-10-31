"""
Utilitaires LiveKit Cloud — sans SDK externe.

LiveKit utilise des tokens JWT signés HS256 pour l'authentification.
Ce module les génère manuellement avec les bibliothèques standard Python
(hmac, hashlib, base64, json) — aucune dépendance supplémentaire.

Variables d'environnement requises sur Render :
  LIVEKIT_URL       : wss://mon-projet.livekit.cloud
  LIVEKIT_API_KEY   : APInnnnnnn
  LIVEKIT_API_SECRET: <secret>

Si ces variables sont absentes, les fonctions retournent None sans lever
d'exception — la plateforme continue de fonctionner, LiveKit est simplement
désactivé.
"""
import os
import json
import hmac
import time
import hashlib
import base64
import secrets
import logging
import urllib.request
import urllib.error
import urllib.parse

logger = logging.getLogger(__name__)

LIVEKIT_URL = os.environ.get("LIVEKIT_URL", "")
LIVEKIT_API_KEY = os.environ.get("LIVEKIT_API_KEY", "")
LIVEKIT_API_SECRET = os.environ.get("LIVEKIT_API_SECRET", "")

_LIVEKIT_ACTIF = bool(LIVEKIT_URL and LIVEKIT_API_KEY and LIVEKIT_API_SECRET)


# ---------------------------------------------------------------------------
# JWT minimal HS256
# ---------------------------------------------------------------------------

def _b64url(data: bytes) -> str:
    """Base64url sans padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _signer_jwt(payload: dict) -> str:
    """Génère un JWT HS256 signé avec LIVEKIT_API_SECRET."""
    header = {"alg": "HS256", "typ": "JWT"}
    parts = _b64url(json.dumps(header, separators=(",", ":")).encode())
    parts += "." + _b64url(json.dumps(payload, separators=(",", ":")).encode())
    sig = hmac.new(
        LIVEKIT_API_SECRET.encode(),
        parts.encode(),
        hashlib.sha256,
    ).digest()
    return parts + "." + _b64url(sig)


# ---------------------------------------------------------------------------
# Génération des tokens participants / formateur
# ---------------------------------------------------------------------------

def generer_token_participant(room_name: str, identite: str, prenom: str) -> str | None:
    """
    Token JWT pour un participant (peut rejoindre la salle, ne peut pas
    désactiver le micro d'un autre ni supprimer la salle).
    """
    if not _LIVEKIT_ACTIF:
        return None
    now = int(time.time())
    payload = {
        "iss": LIVEKIT_API_KEY,
        "sub": identite,
        "iat": now,
        "exp": now + 7200,  # valide 2h
        "jti": secrets.token_hex(8),
        "name": prenom,
        "video": {
            "roomJoin": True,
            "room": room_name,
            "canPublish": True,
            "canSubscribe": True,
            "canPublishData": True,
        },
    }
    return _signer_jwt(payload)


def generer_token_formateur(room_name: str) -> str | None:
    """
    Token JWT pour Laurence (formateur / admin de la salle).
    Peut admettre des participants, voir la salle d'attente, etc.
    """
    if not _LIVEKIT_ACTIF:
        return None
    now = int(time.time())
    payload = {
        "iss": LIVEKIT_API_KEY,
        "sub": "formateur-laurence",
        "iat": now,
        "exp": now + 14400,  # valide 4h
        "jti": secrets.token_hex(8),
        "name": "Laurence",
        "video": {
            "roomJoin": True,
            "room": room_name,
            "roomAdmin": True,
            "canPublish": True,
            "canSubscribe": True,
            "canPublishData": True,
        },
    }
    return _signer_jwt(payload)


# ---------------------------------------------------------------------------
# API REST LiveKit (création de salle)
# ---------------------------------------------------------------------------

def _appel_api(methode: str, chemin: str, corps: dict | None = None) -> dict | None:
    """
    Appel à l'API HTTP LiveKit avec authentification JWT.
    Retourne le dict JSON de réponse ou None en cas d'erreur.
    """
    if not _LIVEKIT_ACTIF:
        return None

    url_base = LIVEKIT_URL.replace("wss://", "https://").replace("ws://", "http://")
    url = url_base + chemin

    now = int(time.time())
    token = _signer_jwt({
        "iss": LIVEKIT_API_KEY,
        "sub": "server",
        "iat": now,
        "exp": now + 60,
        "video": {"roomCreate": True, "roomList": True, "roomAdmin": True},
    })

    data = json.dumps(corps or {}).encode()
    req = urllib.request.Request(
        url, data=data, method=methode,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        logger.error("LiveKit API %s %s → HTTP %s : %s", methode, chemin, e.code, e.read())
        return None
    except Exception as e:
        logger.error("LiveKit API %s %s → %s", methode, chemin, e)
        return None


def creer_salle(room_name: str, max_participants: int = 6) -> bool:
    """
    Crée (ou s'assure de l'existence de) une salle LiveKit.
    Retourne True si succès, False sinon.
    """
    if not _LIVEKIT_ACTIF:
        return False
    resultat = _appel_api("POST", "/twirp/livekit.RoomService/CreateRoom", {
        "name": room_name,
        "max_participants": max_participants,
        "empty_timeout": 3600,      # salle expirée après 1h sans participant
        "departure_timeout": 300,   # salle fermée 5 min après que tout le monde part
    })
    if resultat is not None:
        logger.info("LiveKit salle créée : %s", room_name)
        return True
    return False


def generer_nom_salle(reservation_id: int) -> str:
    """Nom de salle déterministe et lisible."""
    return f"seance-{reservation_id}-{secrets.token_hex(4)}"


def livekit_actif() -> bool:
    """Indique si LiveKit est configuré sur ce déploiement."""
    return _LIVEKIT_ACTIF


# ---------------------------------------------------------------------------
# Actions sur les participants (côté serveur via API REST LiveKit)
# ---------------------------------------------------------------------------

def expulser_participant(room_name: str, identity: str) -> bool:
    """
    Expulse immédiatement un participant de la salle (côté serveur).
    La déconnexion est forcée par le serveur LiveKit, le client n'a pas son mot à dire.
    """
    if not _LIVEKIT_ACTIF:
        return False
    resultat = _appel_api("POST", "/twirp/livekit.RoomService/RemoveParticipant", {
        "room": room_name,
        "identity": identity,
    })
    if resultat is not None:
        logger.info("LiveKit : participant %s expulsé de %s", identity, room_name)
        return True
    return False


def muter_participant_serveur(room_name: str, identity: str, track_sid: str, muted: bool) -> bool:
    """
    Coupe ou réactive le micro d'un participant côté serveur LiveKit.
    track_sid : identifiant de la piste audio (récupéré depuis les métadonnées du participant).
    muted=True  → coupe le micro
    muted=False → réactive (mais l'élève reste maître de son propre micro)
    """
    if not _LIVEKIT_ACTIF:
        return False
    resultat = _appel_api("POST", "/twirp/livekit.RoomService/MutePublishedTrack", {
        "room": room_name,
        "identity": identity,
        "track_sid": track_sid,
        "muted": muted,
    })
    if resultat is not None:
        action = "coupé" if muted else "réactivé"
        logger.info("LiveKit : micro de %s %s dans %s", identity, action, room_name)
        return True
    return False


def lister_participants(room_name: str) -> list:
    """
    Retourne la liste des participants actifs dans la salle avec leurs pistes.
    Utile pour obtenir les track_sid avant un mute serveur.
    """
    if not _LIVEKIT_ACTIF:
        return []
    resultat = _appel_api("POST", "/twirp/livekit.RoomService/ListParticipants", {
        "room": room_name,
    })
    if resultat and "participants" in resultat:
        return resultat["participants"]
    return []


def terminer_salle(room_name: str) -> bool:
    """
    Ferme la salle et expulse tous les participants (fin de séance côté serveur).
    """
    if not _LIVEKIT_ACTIF:
        return False
    resultat = _appel_api("POST", "/twirp/livekit.RoomService/DeleteRoom", {
        "room": room_name,
    })
    if resultat is not None:
        logger.info("LiveKit salle supprimée : %s", room_name)
        return True
    return False
