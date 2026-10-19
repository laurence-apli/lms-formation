"""Liens de réservation Resalib — seul agenda utilisé (l'ancien suivi des jours
d'accompagnement et Cal.com sont abandonnés).

Format des liens directs : https://www.resalib.fr/agenda/66795#/<agenda>/<prestation>
(ou /<agenda>/<IN-PERSON|TELECONSULTATION>/<prestation>). Les libellés doivent être
EXACTEMENT ceux de Resalib : si une prestation est renommée dans Resalib, le lien
ne présélectionne plus rien → le mettre à jour ici.
"""
from urllib.parse import quote

RESALIB_AGENDA = "https://www.resalib.fr/agenda/66795"


def _lien(prestation: str, mode: str = "") -> str:
    chemin = "Cabinet/" + (mode + "/" if mode else "") + quote(prestation, safe="")
    return f"{RESALIB_AGENDA}#/{chemin}"


# Séances comprises dans un accompagnement (Rebirth, Le Temps des Essentielles)
RESALIB_SUIVI = _lien("Séance de suivi – accompagnement en cours (Rebirth, Le Temps des Essentielles)")

LIENS_PRESTATIONS = {
    "adulte_cabinet": _lien("Pratique énergétique adulte (en cabinet)"),
    "enfant_cabinet": _lien("Pratique énergétique enfant (en cabinet)"),
    "adulte_distance": _lien("Pratique énergétique adulte (à distance)", "TELECONSULTATION"),
    "eclore": _lien("Éclore – séance intensive de coaching (3 h, en cabinet)"),
    "suivi": RESALIB_SUIVI,
    "cercle": _lien("Cercle de femme"),
}
