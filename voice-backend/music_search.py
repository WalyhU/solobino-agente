"""Resolución de música con la API pública de búsqueda de iTunes (sin clave).

Sirve para que el modelo no invente títulos: el nombre y el enlace del álbum
provienen del catálogo real de Apple Music.
"""
import difflib
import os
import unicodedata
from dataclasses import dataclass

import httpx

SEARCH_URL = "https://itunes.apple.com/search"
LOOKUP_URL = "https://itunes.apple.com/lookup"
COUNTRY = os.getenv("ITUNES_COUNTRY", "GT")
# Los sencillos y EP suelen ser más recientes que el último álbum de estudio.
FULL_ALBUM_MIN_TRACKS = 5


@dataclass(frozen=True)
class Release:
    label: str
    artist: str
    release_date: str
    web_url: str

    @property
    def app_url(self) -> str:
        """`musics:` abre el enlace en la app de Apple Music, no en el navegador."""
        return self.web_url.replace("https://", "musics://", 1)

    @property
    def year(self) -> str:
        return self.release_date[:4]


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFD", text.casefold())
    return "".join(c for c in text if unicodedata.category(c) != "Mn").strip()


def _to_release(item: dict) -> Release:
    return Release(
        label=item.get("collectionName") or item.get("trackName", ""),
        artist=item.get("artistName", ""),
        release_date=item.get("releaseDate", ""),
        web_url=(item.get("collectionViewUrl") or item.get("trackViewUrl", "")).split("?")[0],
    )


def _pick_latest(items: list[dict]) -> dict:
    full = [i for i in items if i.get("trackCount", 0) >= FULL_ALBUM_MIN_TRACKS]
    return max(full or items, key=lambda i: i.get("releaseDate", ""))


def _pick_best_match(items: list[dict], query: str) -> dict:
    wanted = _normalize(query)
    names = {_normalize(i.get("collectionName") or i.get("trackName", "")): i for i in items}
    close = difflib.get_close_matches(wanted, list(names), n=1, cutoff=0.45)
    if close:
        return names[close[0]]
    contains = [name for name in names if wanted in name or name in wanted]
    return names[contains[0]] if contains else items[0]


async def _artist_albums(query: str, client: httpx.AsyncClient) -> list[dict]:
    """Discografía del artista. Evita tributos y versiones de otros intérpretes."""
    response = await client.get(SEARCH_URL, params={
        "term": query, "entity": "musicArtist", "limit": 5, "country": COUNTRY,
    }, timeout=10)
    response.raise_for_status()
    artists = response.json().get("results", [])
    if not artists:
        return []
    wanted = _normalize(query)
    exact = [a for a in artists if _normalize(a.get("artistName", "")) == wanted]
    artist = (exact or artists)[0]
    response = await client.get(LOOKUP_URL, params={
        "id": artist["artistId"], "entity": "album", "limit": 200, "country": COUNTRY,
    }, timeout=10)
    response.raise_for_status()
    # El primer resultado del lookup es el propio artista, no un álbum.
    return [i for i in response.json().get("results", [])
            if i.get("wrapperType") == "collection"
            and _normalize(i.get("artistName", "")) == _normalize(artist["artistName"])]


async def find_release(query: str, scope: str, client: httpx.AsyncClient) -> Release | None:
    """scope: 'latest_album' | 'album' | 'song'."""
    if scope == "latest_album":
        albums = await _artist_albums(query, client)
        if albums:
            return _to_release(_pick_latest(albums))
        # Sin artista identificado se cae a la búsqueda general.
    entity = "song" if scope == "song" else "album"
    response = await client.get(SEARCH_URL, params={
        "term": query, "entity": entity, "limit": 50, "country": COUNTRY,
    }, timeout=10)
    response.raise_for_status()
    items = [i for i in response.json().get("results", []) if i.get("artistName")]
    if not items:
        return None
    chosen = _pick_latest(items) if scope == "latest_album" else _pick_best_match(items, query)
    release = _to_release(chosen)
    return release if release.web_url else None
