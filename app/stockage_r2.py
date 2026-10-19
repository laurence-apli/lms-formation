"""Stockage des fichiers médias sur Cloudflare R2 (compatible S3).

Pourquoi : les fichiers en base64 dans Neon consomment le stockage (1 Go) ET le
transfert (5 Go/mois) à chaque écoute. R2 : 10 Go gratuits, transfert gratuit.

Fonctionnement :
- Le bucket est PRIVÉ. Un média stocké sur R2 a en base une url courte "r2:<clé>".
- Pour le lire, /medias/<type>/<id>/fichier vérifie les droits de l'élève puis
  redirige vers une URL signée valable quelques heures (le fichier ne passe ni par
  Render ni par Neon).
- Inactif tant que les 4 variables d'environnement R2_* ne sont pas sur Render :
  dans ce cas, tout continue comme avant (base64).

Signature AWS SigV4 écrite à la main (pas de boto3 : trop lourd pour les 512 Mo de Render).
"""
import datetime
import hashlib
import hmac
import logging
import os
import re
import unicodedata
import uuid
from urllib.parse import quote

import httpx

log = logging.getLogger("stockage_r2")

R2_ACCOUNT_ID = os.environ.get("R2_ACCOUNT_ID", "")
R2_ACCESS_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY", "")
R2_BUCKET = os.environ.get("R2_BUCKET", "")

PREFIXE = "r2:"
REGION = "auto"
SERVICE = "s3"
DUREE_URL_SIGNEE = 4 * 3600  # 4 h : de quoi écouter un long audio d'une traite


def r2_actif() -> bool:
    return bool(R2_ACCOUNT_ID and R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY and R2_BUCKET)


def _hote() -> str:
    return f"{R2_ACCOUNT_ID}.r2.cloudflarestorage.com"


def _chemin(cle: str) -> str:
    return "/" + R2_BUCKET + "/" + quote(cle, safe="/-_.~")


def _hmac(cle: bytes, msg: str) -> bytes:
    return hmac.new(cle, msg.encode("utf-8"), hashlib.sha256).digest()


def _cle_signature(date_courte: str) -> bytes:
    k = _hmac(("AWS4" + R2_SECRET_ACCESS_KEY).encode("utf-8"), date_courte)
    k = _hmac(k, REGION)
    k = _hmac(k, SERVICE)
    return _hmac(k, "aws4_request")


def _signer(methode: str, chemin: str, requete: dict, entetes: dict, hash_contenu: str, maintenant):
    """Renvoie (signature, en-têtes signés, portée) selon SigV4."""
    amz_date = maintenant.strftime("%Y%m%dT%H%M%SZ")
    date_courte = maintenant.strftime("%Y%m%d")
    portee = f"{date_courte}/{REGION}/{SERVICE}/aws4_request"
    requete_canonique = "&".join(
        f"{quote(k, safe='-_.~')}={quote(str(v), safe='-_.~')}" for k, v in sorted(requete.items()))
    noms = sorted(k.lower() for k in entetes)
    entetes_canon = "".join(f"{k}:{str(entetes_bas).strip()}\n" for k, entetes_bas in
                            sorted((k.lower(), v) for k, v in entetes.items()))
    signes = ";".join(noms)
    canonique = "\n".join([methode, chemin, requete_canonique, entetes_canon, signes, hash_contenu])
    a_signer = "\n".join(["AWS4-HMAC-SHA256", amz_date, portee,
                          hashlib.sha256(canonique.encode("utf-8")).hexdigest()])
    signature = hmac.new(_cle_signature(date_courte), a_signer.encode("utf-8"), hashlib.sha256).hexdigest()
    return signature, signes, portee, amz_date


def _requete(methode: str, cle: str, contenu=None, type_mime: str = None, taille: int = None):
    maintenant = datetime.datetime.utcnow()
    chemin = _chemin(cle)
    entetes = {"host": _hote(), "x-amz-content-sha256": "UNSIGNED-PAYLOAD",
               "x-amz-date": maintenant.strftime("%Y%m%dT%H%M%SZ")}
    if type_mime:
        entetes["content-type"] = type_mime
    signature, signes, portee, _ = _signer(methode, chemin, {}, entetes, "UNSIGNED-PAYLOAD", maintenant)
    entetes["authorization"] = (f"AWS4-HMAC-SHA256 Credential={R2_ACCESS_KEY_ID}/{portee}, "
                                f"SignedHeaders={signes}, Signature={signature}")
    if taille is not None:
        entetes["content-length"] = str(taille)
    return httpx.request(methode, "https://" + _hote() + chemin, headers=entetes,
                         content=contenu, timeout=httpx.Timeout(600.0, connect=20.0))


def _nom_propre(nom: str) -> str:
    nom = unicodedata.normalize("NFKD", nom or "fichier").encode("ascii", "ignore").decode()
    nom = re.sub(r"[^A-Za-z0-9._-]+", "-", nom).strip("-.")
    return (nom or "fichier")[-80:]


def nouvelle_cle(dossier: str, nom_fichier: str) -> str:
    """Ex. medias/chapitre/42/3f9c…-meditation.mp3 (le hasard rend l'adresse impossible à deviner)."""
    return f"{dossier.strip('/')}/{uuid.uuid4().hex[:12]}-{_nom_propre(nom_fichier)}"


def envoyer(cle: str, contenu, type_mime: str, taille: int) -> str:
    """Dépose le fichier (bytes ou fichier ouvert, lu en flux) et renvoie l'url à stocker en base."""
    if hasattr(contenu, "read"):
        flux = contenu

        def morceaux():
            while True:
                bloc = flux.read(1024 * 1024)
                if not bloc:
                    break
                yield bloc
        corps = morceaux()
    else:
        corps = contenu
    r = _requete("PUT", cle, corps, type_mime or "application/octet-stream", taille)
    if r.status_code not in (200, 201):
        log.error("R2 PUT %s -> %s %s", cle, r.status_code, r.text[:300])
        raise RuntimeError(f"Envoi vers R2 refusé ({r.status_code}).")
    return PREFIXE + cle


def infos_objet(cle: str):
    """(taille en octets, ETag sans guillemets = MD5 du fichier pour un envoi simple) ou (None, None)."""
    r = _requete("HEAD", cle)
    if r.status_code != 200:
        return None, None
    return int(r.headers.get("content-length", "0")), r.headers.get("etag", "").strip('"')


def taille_objet(cle: str):
    return infos_objet(cle)[0]


def supprimer(url: str) -> None:
    """Supprime l'objet R2 (sans erreur bloquante : la suppression du média en base prime)."""
    if not (url and url.startswith(PREFIXE) and r2_actif()):
        return
    try:
        r = _requete("DELETE", url[len(PREFIXE):])
        if r.status_code not in (200, 204, 404):
            log.warning("R2 DELETE %s -> %s", url, r.status_code)
    except Exception as e:  # noqa: BLE001
        log.warning("R2 DELETE %s impossible : %s", url, e)


def url_signee(url: str, telecharger_sous: str = None, duree: int = DUREE_URL_SIGNEE) -> str:
    """URL de lecture temporaire pour un média "r2:<clé>"."""
    cle = url[len(PREFIXE):]
    maintenant = datetime.datetime.utcnow()
    chemin = _chemin(cle)
    portee_date = maintenant.strftime("%Y%m%d")
    requete = {
        "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
        "X-Amz-Credential": f"{R2_ACCESS_KEY_ID}/{portee_date}/{REGION}/{SERVICE}/aws4_request",
        "X-Amz-Date": maintenant.strftime("%Y%m%dT%H%M%SZ"),
        "X-Amz-Expires": str(duree),
        "X-Amz-SignedHeaders": "host",
    }
    if telecharger_sous:
        requete["response-content-disposition"] = f'attachment; filename="{_nom_propre(telecharger_sous)}"'
    signature, _, _, _ = _signer("GET", chemin, requete, {"host": _hote()}, "UNSIGNED-PAYLOAD", maintenant)
    requete["X-Amz-Signature"] = signature
    qs = "&".join(f"{quote(k, safe='-_.~')}={quote(str(v), safe='-_.~')}" for k, v in sorted(requete.items()))
    return f"https://{_hote()}{chemin}?{qs}"
