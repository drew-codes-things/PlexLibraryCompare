from collections import defaultdict

from compare import normalize_title


def find_duplicate_shows(scanned_shows):
    groups = defaultdict(list)
    for show in scanned_shows:
        key = (show["library_name"], normalize_title(show["title"]), show["year"])
        groups[key].append(show)

    duplicates = []
    for key, items in groups.items():
        if len(items) > 1:
            duplicates.append({
                "library_name": key[0],
                "normalized_title": key[1],
                "year": key[2],
                "count": len(items),
                "items": items,
            })
    return duplicates
