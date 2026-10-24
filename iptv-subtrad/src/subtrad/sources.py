"""Sources de playlists : un lien M3U, un fichier M3U, ou un serveur (adresse + identifiant +
mot de passe, le format des services IPTV « Xtream »).

Une source garde ses identifiants chez elle ; la page n'en voit que `public()` (nom, type et
adresse du serveur sans identifiant ni chemin).
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from urllib.parse import urlencode, urlparse

KINDS = {"m3u": "Lien M3U", "xtream": "Serveur (identifiant + mot de passe)", "fichier": "Fichier M3U"}
SLOT_SIZE = 10_000_000  # numéros de vidéo réservés à chaque source (voir Library)


def normalize_server(server: str) -> str:
    """`ma.box:8080`, `http://ma.box/get.php?...` -> `http://ma.box:8080` (schéma + hôte)."""
    server = server.strip()
    if not server:
        raise ValueError("L'adresse du serveur est vide.")
    if "://" not in server:
        server = "http://" + server
    parsed = urlparse(server)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Adresse de serveur invalide (exemple : http://monserveur.com:8080).")
    return f"{parsed.scheme}://{parsed.netloc.rsplit('@', 1)[-1]}"


def xtream_playlist_url(server: str, username: str, password: str) -> str:
    """Lien de playlist d'un service Xtream : `<serveur>/get.php?username=…&password=…`."""
    query = urlencode({"username": username, "password": password,
                       "type": "m3u_plus", "output": "ts"})
    return f"{normalize_server(server)}/get.php?{query}"


def host_of(url: str) -> str:
    """`monserveur.com:8080` : l'hôte seulement, jamais le chemin ni les identifiants."""
    parsed = urlparse(url if "://" in url else "http://" + url)
    if not parsed.hostname:
        return ""
    return parsed.hostname + (f":{parsed.port}" if parsed.port else "")


@dataclass
class Source:
    name: str
    kind: str  # "m3u" | "xtream" | "fichier"
    slot: int  # numérote les vidéos de cette source ; ne change jamais
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    url: str = ""  # lien M3U
    server: str = ""
    username: str = ""
    password: str = ""
    count: int = 0
    updated_at: float = 0.0
    error: str = ""

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"Type de source inconnu : {self.kind}")

    @property
    def refreshable(self) -> bool:
        return self.kind != "fichier"

    def playlist_url(self) -> str:
        if self.kind == "xtream":
            return xtream_playlist_url(self.server, self.username, self.password)
        if self.kind == "m3u":
            return self.url
        raise ValueError("Un fichier ne se recharge pas : ajoute-le à nouveau.")

    def host(self) -> str:
        if self.kind == "xtream":
            return host_of(self.server)
        return host_of(self.url) if self.kind == "m3u" else "fichier"

    def public(self) -> dict:
        """Ce que voit la page : jamais le lien complet, l'identifiant ni le mot de passe."""
        return {"id": self.id, "name": self.name, "kind": self.kind,
                "kind_label": KINDS[self.kind], "host": self.host(), "count": self.count,
                "updated_at": self.updated_at, "error": self.error,
                "refreshable": self.refreshable}

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Source":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


def build_source(kind: str, name: str, slot: int, url: str = "", server: str = "",
                 username: str = "", password: str = "") -> Source:
    """Crée une source en validant ce que l'utilisateur a saisi."""
    if kind == "m3u":
        url = url.strip()
        if not url.startswith(("http://", "https://")):
            raise ValueError("Le lien doit commencer par http:// ou https://.")
        return Source(name=name.strip() or host_of(url) or "Playlist", kind=kind, slot=slot, url=url)
    if kind == "xtream":
        server = normalize_server(server)
        username, password = username.strip(), password.strip()
        if not username or not password:
            raise ValueError("L'identifiant et le mot de passe sont obligatoires.")
        return Source(name=name.strip() or host_of(server), kind=kind, slot=slot, server=server,
                      username=username, password=password)
    if kind == "fichier":
        return Source(name=name.strip() or "Fichier M3U", kind=kind, slot=slot)
    raise ValueError(f"Type de source inconnu : {kind}")
