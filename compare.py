import re
import unicodedata


def normalize_title(title: str) -> str:
    title = unicodedata.normalize("NFKC", title)
    title = title.lower().strip()
    title = re.sub(r"[\[\](){}:;,'’!.?-]", " ", title)
    title = re.sub(r"\s+", " ", title)
    return title.strip()


def build_match_key(title: str, year):
    base = normalize_title(title)
    return f"{base}::{year}" if year else base


def to_lookup(scanned_shows):
    lookup = {}
    for show in scanned_shows:
        key = build_match_key(show["title"], show["year"])
        lookup[key] = show
    return lookup


def find_episode_mismatches(low_seasons, high_seasons):
    """For seasons present in both libraries, find episode numbers missing on either side."""
    low_by_number = {s["season_number"]: s for s in low_seasons}
    high_by_number = {s["season_number"]: s for s in high_seasons}
    common_seasons = sorted(set(low_by_number) & set(high_by_number))

    mismatches = []
    for season_number in common_seasons:
        low_season = low_by_number[season_number]
        high_season = high_by_number[season_number]
        low_episodes = set(low_season["episode_numbers"])
        high_episodes = set(high_season["episode_numbers"])
        missing_in_high = sorted(low_episodes - high_episodes)
        missing_in_low = sorted(high_episodes - low_episodes)
        if missing_in_high or missing_in_low:
            mismatches.append({
                "season_number": season_number,
                "low_episode_count": low_season["episode_count"],
                "high_episode_count": high_season["episode_count"],
                "missing_in_high": missing_in_high,
                "missing_in_low": missing_in_low,
            })
    return mismatches


def compare_libraries(low_shows, high_shows):
    low_lookup = to_lookup(low_shows)
    high_lookup = to_lookup(high_shows)
    all_keys = sorted(set(low_lookup) | set(high_lookup))

    results = []
    for key in all_keys:
        low = low_lookup.get(key)
        high = high_lookup.get(key)

        if low and not high:
            low_seasons = sorted(s["season_number"] for s in low["seasons"])
            results.append({
                "title": low["title"],
                "year": low["year"],
                "status": "missing_in_high",
                "low_seasons": low_seasons,
                "high_seasons": [],
                "missing_in_high": low_seasons,
                "missing_in_low": [],
                "episode_mismatches": [],
                "low_exists": True,
                "high_exists": False,
                "plex_url_low": low["plex_web_url"],
                "plex_url_high": None,
            })
            continue

        if high and not low:
            high_seasons = sorted(s["season_number"] for s in high["seasons"])
            results.append({
                "title": high["title"],
                "year": high["year"],
                "status": "high_only",
                "low_seasons": [],
                "high_seasons": high_seasons,
                "missing_in_high": [],
                "missing_in_low": high_seasons,
                "episode_mismatches": [],
                "low_exists": False,
                "high_exists": True,
                "plex_url_low": None,
                "plex_url_high": high["plex_web_url"],
            })
            continue

        low_seasons = sorted(s["season_number"] for s in low["seasons"])
        high_seasons = sorted(s["season_number"] for s in high["seasons"])
        missing_in_high = sorted(set(low_seasons) - set(high_seasons))
        missing_in_low = sorted(set(high_seasons) - set(low_seasons))
        episode_mismatches = find_episode_mismatches(low["seasons"], high["seasons"])

        status = "match_complete"
        if missing_in_high or missing_in_low or episode_mismatches:
            status = "season_mismatch"

        results.append({
            "title": low["title"],
            "year": low["year"],
            "status": status,
            "low_seasons": low_seasons,
            "high_seasons": high_seasons,
            "missing_in_high": missing_in_high,
            "missing_in_low": missing_in_low,
            "episode_mismatches": episode_mismatches,
            "low_exists": True,
            "high_exists": True,
            "plex_url_low": low["plex_web_url"],
            "plex_url_high": high["plex_web_url"],
        })

    return results
