from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Optional, Sequence


class MusicSection(str, Enum):
    SONGS = "songs"
    ALBUMS = "albums"
    ARTISTS = "artists"


@dataclass(frozen=True)
class MusicFilters:
    search: str = ""
    genre: Optional[str] = None
    favorites_only: bool = False
    sort_by: str = "Name"
    descending: bool = False


@dataclass(frozen=True)
class PlaybackItem:
    stream_url: str
    title: str
    subtitle: str
    cover_urls: tuple[str, ...]


class MusicLibraryModel:
    """Music-library data access and domain rules.

    The class is deliberately independent from Qt widgets. It owns Jellyfin query
    semantics and media fallback rules, while the controller decides when to call
    it and the view decides how results are rendered.
    """

    _FIELDS = "Album,AlbumId,Artists,ArtistItems,RunTimeTicks,ParentId"
    _SORT_FIELDS = {
        MusicSection.SONGS: {
            "Name": "SortName",
            "Artist": "Artist",
            "Album": "Album",
            "DateCreated": "DateCreated",
            "PlayCount": "PlayCount",
            "Random": "Random",
        },
        MusicSection.ALBUMS: {
            "Name": "SortName",
            "Artist": "AlbumArtist",
            "Album": "SortName",
            "DateCreated": "DateCreated",
            "PlayCount": "PlayCount",
            "Random": "Random",
        },
        MusicSection.ARTISTS: {
            "Name": "SortName",
            "Artist": "SortName",
            "Album": "SortName",
            "DateCreated": "DateCreated",
            "PlayCount": "PlayCount",
            "Random": "Random",
        },
    }

    def __init__(self, client: Any, library_id: str):
        if not library_id:
            raise ValueError("A music library id is required")
        self.client = client
        self.library_id = library_id

    def list_songs(self, filters: MusicFilters) -> list[dict[str, Any]]:
        return self.client.list_items_in_parent(
            self.library_id,
            params=self._query_params(MusicSection.SONGS, filters, "Audio"),
        )

    def list_albums(
        self, filters: MusicFilters, artist_id: Optional[str] = None
    ) -> list[dict[str, Any]]:
        params = self._query_params(MusicSection.ALBUMS, filters, "MusicAlbum")
        if artist_id:
            params["ArtistIds"] = artist_id
        return self.client.list_items_in_parent(self.library_id, params=params)

    def list_artists(self, filters: MusicFilters) -> list[dict[str, Any]]:
        return self.client.list_items_in_parent(
            self.library_id,
            params=self._query_params(MusicSection.ARTISTS, filters, "MusicArtist"),
        )

    def list_album_tracks(self, album_id: str) -> list[dict[str, Any]]:
        if not album_id:
            return []
        params = {
            "IncludeItemTypes": "Audio",
            "Recursive": True,
            "Fields": self._FIELDS,
            "SortBy": "ParentIndexNumber,IndexNumber,SortName",
            "SortOrder": "Ascending",
        }
        return self.client.list_items_in_parent(album_id, params=params)

    def list_genres(self) -> list[str]:
        data = self.client.list_item_filters(
            self.library_id, include_item_types="Audio"
        )
        return self.extract_genres(data)

    def item_cover_urls(
        self, item: Mapping[str, Any], max_side: int
    ) -> tuple[str, ...]:
        return self._urls_for_ids((item.get("Id"),), max_side)

    def track_cover_urls(
        self,
        track: Mapping[str, Any],
        max_side: int,
        album_fallback_url: Optional[str] = None,
        artist_fallback_id: Optional[str] = None,
    ) -> tuple[str, ...]:
        """Return cover candidates in business-preference order.

        A URL can exist syntactically while Jellyfin responds with a missing image,
        so the view-side loader tries each candidate until one decodes successfully.
        """

        artist_id = self.first_artist_id(track) or artist_fallback_id
        urls = list(
            self._urls_for_ids(
                (track.get("Id"), track.get("AlbumId"), artist_id), max_side
            )
        )
        if album_fallback_url:
            album_position = 1 if track.get("Id") else 0
            urls.insert(album_position, album_fallback_url)
        return self._unique_strings(urls)

    def playback_item(
        self,
        track: Mapping[str, Any],
        album_fallback_url: Optional[str] = None,
        artist_fallback_id: Optional[str] = None,
    ) -> Optional[PlaybackItem]:
        item_id = track.get("Id")
        if not item_id:
            return None
        return PlaybackItem(
            stream_url=self.client.stream_url_for_track(item_id),
            title=track.get("Name") or "",
            subtitle=", ".join(track.get("Artists") or []),
            cover_urls=self.track_cover_urls(
                track,
                400,
                album_fallback_url=album_fallback_url,
                artist_fallback_id=artist_fallback_id,
            ),
        )

    @staticmethod
    def first_artist_id(track: Mapping[str, Any]) -> Optional[str]:
        artist_items = track.get("ArtistItems") or []
        if isinstance(artist_items, list):
            for entry in artist_items:
                if isinstance(entry, dict) and entry.get("Id"):
                    return entry["Id"]
        artist_ids = track.get("ArtistIds") or []
        if isinstance(artist_ids, list) and artist_ids:
            return artist_ids[0]
        return None

    @staticmethod
    def extract_genres(data: Any) -> list[str]:
        if isinstance(data, dict) and isinstance(data.get("Genres"), list):
            genres = [
                value.get("Name") if isinstance(value, dict) else value
                for value in data["Genres"][:50]
            ]
            return list(dict.fromkeys(value for value in genres if value))
        groups = data.get("Filters") if isinstance(data, dict) else None
        if not isinstance(groups, list):
            return []
        for group in groups:
            name = group.get("Name", "") if isinstance(group, dict) else ""
            if "genre" not in name.lower():
                continue
            values = group.get("Values") or []
            genres = [
                value.get("Name")
                for value in values[:50]
                if isinstance(value, dict) and value.get("Name")
            ]
            return list(dict.fromkeys(genres))
        return []

    def _query_params(
        self, section: MusicSection, filters: MusicFilters, item_type: str
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "IncludeItemTypes": item_type,
            "Recursive": True,
            "Fields": self._FIELDS,
            "SortBy": self._SORT_FIELDS[section].get(filters.sort_by, "SortName"),
            "SortOrder": "Descending" if filters.descending else "Ascending",
            "StartIndex": 0,
            "Limit": 200,
        }
        search = filters.search.strip()
        if search:
            params["SearchTerm"] = search
        if filters.favorites_only:
            params["IsFavorite"] = True
        if filters.genre:
            params["Genres"] = filters.genre
        return params

    def _urls_for_ids(self, item_ids: Sequence[Any], max_side: int) -> tuple[str, ...]:
        urls: list[str] = []
        for item_id in item_ids:
            if not item_id:
                continue
            try:
                url = self.client.image_url_for_item(item_id, "Primary", max_side)
            except Exception:
                continue
            if url:
                urls.append(url)
        return self._unique_strings(urls)

    @staticmethod
    def _unique_strings(values: Sequence[str]) -> tuple[str, ...]:
        return tuple(dict.fromkeys(value for value in values if value))
