from typing import Dict


def music_query_params(library_id: str) -> Dict[str, str]:
    """Return the standard query params used by the Music library view when
    querying items within a selected music library.

    This centralizes music-specific query parameters so the controller can
    reuse the existing music-item behavior without duplicating literals.
    """
    return {
        "IncludeItemTypes": "Audio",
        "Recursive": True,
        "Fields": "Album,Artists,RunTimeTicks,ParentId",
        "SortBy": "SortName",
        "SortOrder": "Ascending",
    }
