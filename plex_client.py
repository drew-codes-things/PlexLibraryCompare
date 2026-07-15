import os

from plexapi.myplex import MyPlexAccount


def get_plex():
    token = os.getenv("PLEX_TOKEN")
    server_name = os.getenv("PLEX_SERVER_NAME")
    if not token or not server_name:
        raise RuntimeError("PLEX_TOKEN and PLEX_SERVER_NAME must be set (see .env.example).")
    account = MyPlexAccount(token=token)
    return account.resource(server_name).connect()


def get_library_sections(plex):
    low_name = os.getenv("LOW_LIBRARY_NAME", "Anime Shows")
    high_name = os.getenv("HIGH_LIBRARY_NAME", "Anime Shows - High")
    low_section = plex.library.section(low_name)
    high_section = plex.library.section(high_name)
    return low_section, high_section


if __name__ == "__main__":
    from dotenv import load_dotenv

    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    load_dotenv(os.path.join(BASE_DIR, ".env"))

    plex = get_plex()
    print(f"Connected to Plex server: {plex.friendlyName}")

    low_section, high_section = get_library_sections(plex)
    print(f"Low library:  {low_section.title}")
    print(f"High library: {high_section.title}")
