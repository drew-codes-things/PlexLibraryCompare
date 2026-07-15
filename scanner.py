from tqdm import tqdm


def extract_seasons(show):
    seasons = []
    for season in show.seasons():
        episodes = season.episodes()
        episode_numbers = sorted(e.index for e in episodes if e.index is not None)
        seasons.append({
            "season_rating_key": season.ratingKey,
            "season_number": season.index,
            "season_title": season.title,
            "episode_count": len(episodes),
            "episode_numbers": episode_numbers,
        })
    return seasons


def extract_show_data(show, library_name):
    return {
        "rating_key": show.ratingKey,
        "title": show.title,
        "year": getattr(show, "year", None),
        "library_name": library_name,
        "plex_web_url": show.getWebURL(),
        "seasons": extract_seasons(show),
    }


def scan_library(section, on_progress=None, show_cli_progress=True):
    shows = section.search(libtype="show")
    total = len(shows)
    scanned = []
    iterator = tqdm(shows, desc=f"Scanning {section.title}", unit="show", disable=not show_cli_progress)
    for i, show in enumerate(iterator, start=1):
        scanned.append(extract_show_data(show, section.title))
        if on_progress:
            on_progress(section.title, i, total)
    return scanned
