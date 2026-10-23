"""Messages d'erreur lisibles, sans jamais laisser fuiter un lien de flux.

Les liens IPTV contiennent presque toujours un identifiant et un mot de passe : une erreur
réseau brute les afficherait en clair dans la page ou le Terminal.
"""

from __future__ import annotations

import re

import requests

_URL_RE = re.compile(r"https?://\S+")

_HTTP_HINTS = {
    401: "identifiants refusés",
    403: "accès refusé",
    404: "adresse introuvable",
    429: "trop de requêtes",
    500: "erreur interne du serveur",
    502: "serveur indisponible",
    503: "serveur indisponible ou surchargé",
    504: "le serveur a mis trop de temps à répondre",
}


def redact_urls(text: str) -> str:
    return _URL_RE.sub("[lien]", text)


def friendly_error(exc: BaseException) -> str:
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        code = exc.response.status_code
        hint = f" ({_HTTP_HINTS[code]})" if code in _HTTP_HINTS else ""
        return f"Le serveur du flux a répondu {code}{hint}."
    if isinstance(exc, requests.Timeout):
        return "Le serveur du flux n'a pas répondu à temps."
    if isinstance(exc, requests.ConnectionError):
        return "Impossible de joindre le serveur du flux."
    return redact_urls(str(exc)) or type(exc).__name__
