import argparse
import csv
import os
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import requests
from dotenv import load_dotenv
from rdflib import Graph, Namespace

load_dotenv()

BGG_API_KEY = os.getenv("BGG_API_KEY", "").strip()
BGG_API_URL = "https://boardgamegeek.com/xmlapi2/thing"

BATCH_SIZE = 20
REQUEST_DELAY_SEC = 4.0
MAX_PLAYTIME_PLAYERS_CAP = 12
COOP_MECHANIC_ID = "2023"

DEFAULT_GAME_IDS = [
    284083,  # The Crew: The Quest for Planet Nine
    98778,   # Hanabi
    209778,  # Magic Maze
    822,     # Carcassonne
    2651,    # Power Grid
    174430,  # Gloomhaven
    161936,  # Pandemic Legacy: Season 1
    169786,  # Scythe
    70323,   # King of Tokyo
    31260,   # Agricola
]


def escape_ttl(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r", "")
        .replace("\n", " ")
        .replace("\t", " ")
        .strip()
    )


def load_game_ids_from_csv(csv_path: Path, limit: int, include_defaults: bool = True) -> list[int]:
    ranked_games: list[tuple[int, int]] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("is_expansion", "0").strip() != "0":
                continue
            rank_str = row.get("rank", "").strip()
            id_str = row.get("id", "").strip()
            if rank_str.isdigit() and id_str.isdigit() and int(rank_str) > 0:
                ranked_games.append((int(rank_str), int(id_str)))

    ranked_games.sort(key=lambda pair: pair[0])
    selected = [game_id for _, game_id in ranked_games[:limit]]

    if include_defaults:
        existing = set(selected)
        for default_id in DEFAULT_GAME_IDS:
            if default_id not in existing:
                selected.append(default_id)
                existing.add(default_id)

    return selected


def fetch_bgg_batch(game_ids: list[int], max_retries: int = 8) -> list[ET.Element]:
    params = {"id": ",".join(map(str, game_ids)), "stats": 1}
    headers = {
        "Authorization": f"Bearer {BGG_API_KEY}",
        "User-Agent": "BGG-Ontology-ABox-Generator/2.0",
    }

    for attempt in range(1, max_retries + 1):
        try:
            response = requests.get(BGG_API_URL, params=params, headers=headers, timeout=30)
        except requests.RequestException as exc:
            wait_sec = min(30, attempt * 5)
            print(f"  Network error ({exc}), retrying in {wait_sec}s...")
            time.sleep(wait_sec)
            continue

        if response.status_code == 200:
            root = ET.fromstring(response.content)
            return root.findall("item")

        if response.status_code in (202, 429, 500, 502, 503, 504):
            wait_sec = min(30, attempt * 5)
            print(f"  HTTP {response.status_code}, waiting {wait_sec}s (attempt {attempt}/{max_retries})...")
            time.sleep(wait_sec)
            continue

        response.raise_for_status()

    raise RuntimeError(f"Failed to fetch BGG batch after {max_retries} attempts: {game_ids}")


def fetch_all_games(game_ids: list[int]) -> list[ET.Element]:
    items: list[ET.Element] = []
    total_batches = (len(game_ids) + BATCH_SIZE - 1) // BATCH_SIZE

    for idx in range(0, len(game_ids), BATCH_SIZE):
        batch = game_ids[idx : idx + BATCH_SIZE]
        batch_num = idx // BATCH_SIZE + 1
        print(f"Fetching batch {batch_num}/{total_batches} ({len(batch)} games)...")
        items.extend(fetch_bgg_batch(batch))
        if batch_num < total_batches:
            time.sleep(REQUEST_DELAY_SEC)

    return items


def safe_int(elem: ET.Element | None, attr: str = "value", default: int = 0) -> int:
    if elem is None:
        return default
    raw = (elem.get(attr) or "").strip()
    try:
        return int(raw)
    except ValueError:
        return default


def parse_player_poll(poll_element: ET.Element | None) -> tuple[list[int], list[int]]:
    recommended, best = [], []
    if poll_element is None:
        return recommended, best

    for results in poll_element.findall("results"):
        numplayers = results.get("numplayers", "")
        if not numplayers.isdigit():
            continue
        count = int(numplayers)
        if count <= 0:
            continue

        best_votes, rec_votes, not_rec_votes = 0, 0, 0
        for res in results.findall("result"):
            val = res.get("value")
            votes = int(res.get("numvotes", 0) or 0)
            if val == "Best":
                best_votes = votes
            elif val == "Recommended":
                rec_votes = votes
            elif val == "Not Recommended":
                not_rec_votes = votes

        if best_votes > rec_votes and best_votes > not_rec_votes and best_votes > 0:
            best.append(count)
        if (best_votes + rec_votes) > not_rec_votes and (best_votes + rec_votes) > 0:
            recommended.append(count)

    return sorted(set(recommended)), sorted(set(best))


def generate_turtle(items: list[ET.Element]) -> str:
    lines = [
        "@prefix : <http://example.org/bgo#> .",
        "@prefix bgo: <http://example.org/bgo#> .",
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .",
        "@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
        "@prefix schema: <https://schema.org/> .",
        "@prefix dc: <http://purl.org/dc/elements/1.1/> .",
        "",
        "# =================================================================",
        "# ABox: INSTANCE DATA",
        "# =================================================================",
        "",
    ]

    designers: dict[str, str] = {}
    publishers: dict[str, str] = {}
    mechanics: dict[str, str] = {}
    categories: dict[str, str] = {}
    seen_games: set[str] = set()

    for item in items:
        bgg_id = item.get("id")
        if not bgg_id or bgg_id in seen_games:
            continue
        seen_games.add(bgg_id)

        name_elem = item.find("name[@type='primary']")
        game_title = escape_ttl(name_elem.get("value")) if name_elem is not None else f"Game {bgg_id}"

        year = safe_int(item.find("yearpublished"), default=0)
        min_age = safe_int(item.find("minage"), default=0)

        min_players = max(1, safe_int(item.find("minplayers"), default=1))
        raw_max_players = safe_int(item.find("maxplayers"), default=min_players)
        max_players = raw_max_players if raw_max_players >= min_players else min_players

        fallback_playtime = max(0, safe_int(item.find("playingtime"), default=0))
        min_playtime = max(0, safe_int(item.find("minplaytime"), default=fallback_playtime))
        if min_playtime == 0 and fallback_playtime > 0:
            min_playtime = fallback_playtime
        max_playtime = max(min_playtime, safe_int(item.find("maxplaytime"), default=min_playtime))

        weight_elem = item.find(".//averageweight")
        weight_val = None
        if weight_elem is not None:
            try:
                parsed_w = float(weight_elem.get("value", "0"))
                if parsed_w > 0.0:
                    weight_val = parsed_w
            except ValueError:
                weight_val = None

        game_mechanics = []
        is_cooperative = False
        for link in item.findall("link[@type='boardgamemechanic']"):
            m_id = link.get("id")
            m_val = link.get("value", "")
            if not m_id:
                continue
            mechanics[m_id] = m_val
            game_mechanics.append(f"bgo:mech_{m_id}")
            if m_id == COOP_MECHANIC_ID:
                is_cooperative = True

        game_categories = []
        for link in item.findall("link[@type='boardgamecategory']"):
            c_id = link.get("id")
            c_val = link.get("value", "")
            if not c_id:
                continue
            categories[c_id] = c_val
            game_categories.append(f"bgo:cat_{c_id}")

        game_designers = []
        for link in item.findall("link[@type='boardgamedesigner']"):
            d_id = link.get("id")
            d_val = link.get("value", "")
            if not d_id:
                continue
            designers[d_id] = d_val
            game_designers.append(f"bgo:person_{d_id}")

        game_publishers = []
        for link in item.findall("link[@type='boardgamepublisher']"):
            pub_id = link.get("id")
            pub_val = link.get("value", "")
            if not pub_id:
                continue
            publishers[pub_id] = pub_val
            game_publishers.append(f"bgo:org_{pub_id}")

        player_poll = item.find("poll[@name='suggested_numplayers']")
        recommended_players, best_players = parse_player_poll(player_poll)

        game_class = (
            "owl:NamedIndividual, bgo:BoardGame, bgo:CooperativeGame"
            if is_cooperative
            else "owl:NamedIndividual, bgo:BoardGame, bgo:CompetitiveGame"
        )

        lines.append(f"bgo:game_{bgg_id} a {game_class} ;")
        lines.append(f'    dc:title "{game_title}"@en ;')
        lines.append(f"    bgo:bggId {bgg_id} ;")

        if year > 0:
            lines.append(f'    bgo:yearPublished "{year:04d}"^^xsd:gYear ;')
        if min_age > 0:
            lines.append(f"    bgo:minAge {min_age} ;")
        if weight_val is not None:
            lines.append(f'    bgo:complexityWeight "{weight_val:.2f}"^^xsd:decimal ;')

        for mech_uri in sorted(set(game_mechanics)):
            lines.append(f"    bgo:hasMechanic {mech_uri} ;")
        for cat_uri in sorted(set(game_categories)):
            lines.append(f"    bgo:hasCategory {cat_uri} ;")
        for des_uri in sorted(set(game_designers)):
            lines.append(f"    dc:creator {des_uri} ;")
        for pub_uri in sorted(set(game_publishers)):
            lines.append(f"    dc:publisher {pub_uri} ;")

        player_cfg_lines = [
            "    bgo:hasPlayerConfig [",
            "        a bgo:PlayerConfiguration ;",
            f"        bgo:minPlayers {min_players} ;",
            f"        bgo:maxPlayers {max_players} ;",
        ]
        if recommended_players:
            player_cfg_lines.append(f"        bgo:recommendedPlayers {', '.join(map(str, recommended_players))} ;")
        if best_players:
            player_cfg_lines.append(f"        bgo:bestPlayers {', '.join(map(str, best_players))} ;")

        player_cfg_lines[-1] = player_cfg_lines[-1].rstrip(" ;")
        player_cfg_lines.append("    ] ;")
        lines.extend(player_cfg_lines)

        effective_max = min(max_players, max(min_players, MAX_PLAYTIME_PLAYERS_CAP))
        span = effective_max - min_players
        playtime_step = (max_playtime - min_playtime) / span if span > 0 else 0.0

        for idx, count in enumerate(range(min_players, effective_max + 1)):
            estimated_minutes = round(min_playtime + idx * playtime_step)
            lines.append("    bgo:hasPlaytimeConfig [")
            lines.append("        a bgo:PlaytimeConfiguration ;")
            lines.append(f"        bgo:forPlayerCount {count} ;")
            lines.append(f"        bgo:playtimeMinutes {estimated_minutes}")
            lines.append("    ] ;")

        lines[-1] = lines[-1].rstrip(" ;") + " .\n"

    lines.append("# --- External Entities ---")
    for d_id, d_name in sorted(designers.items(), key=lambda x: int(x[0])):
        escaped = escape_ttl(d_name)
        lines.append(
            f'bgo:person_{d_id} a owl:NamedIndividual, schema:Person ; '
            f'rdfs:label "{escaped}"@en ; schema:name "{escaped}"@en .'
        )

    for pub_id, pub_name in sorted(publishers.items(), key=lambda x: int(x[0])):
        escaped = escape_ttl(pub_name)
        lines.append(
            f'bgo:org_{pub_id} a owl:NamedIndividual, schema:Organization ; '
            f'rdfs:label "{escaped}"@en ; schema:name "{escaped}"@en .'
        )

    for m_id, m_name in sorted(mechanics.items(), key=lambda x: int(x[0])):
        lines.append(
            f'bgo:mech_{m_id} a owl:NamedIndividual, bgo:GameMechanic ; '
            f'rdfs:label "{escape_ttl(m_name)}"@en .'
        )

    for c_id, c_name in sorted(categories.items(), key=lambda x: int(x[0])):
        lines.append(
            f'bgo:cat_{c_id} a owl:NamedIndividual, bgo:GameCategory ; '
            f'rdfs:label "{escape_ttl(c_name)}"@en .'
        )

    return "\n".join(lines)


def merge_ontology(tbox_path: Path, abox_path: Path, output_path: Path) -> None:
    if not tbox_path.exists():
        print(f"Warning: {tbox_path} not found. Skipping merge into {output_path}.", file=sys.stderr)
        return

    g = Graph()
    g.parse(tbox_path, format="turtle")
    g.parse(abox_path, format="turtle")

    g.bind("bgo", Namespace("http://example.org/bgo#"), override=True)
    g.bind("dc", Namespace("http://purl.org/dc/elements/1.1/"), override=True)
    g.bind("schema", Namespace("https://schema.org/"), override=True)

    g.serialize(destination=str(output_path), format="turtle")
    print(f"Merged {tbox_path} + {abox_path} -> {output_path} ({len(g)} triples).")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch BGG data and build ABox + merged OWL ontology.")
    parser.add_argument("--csv", type=Path, default=Path("boardgames_ranks.csv"), help="Path to BGG ranks CSV dump.")
    parser.add_argument("--limit", type=int, default=200, help="Number of top ranked base games to fetch.")
    parser.add_argument("--tbox", type=Path, default=Path("tbox.ttl"), help="Path to TBox Turtle file.")
    parser.add_argument("--abox", type=Path, default=Path("abox.ttl"), help="Output path for generated ABox.")
    parser.add_argument("--output", type=Path, default=Path("ontology.ttl"), help="Output path for merged ontology.")
    parser.add_argument("--ids", nargs="*", type=int, help="Optional explicit BGG IDs instead of CSV.")
    args = parser.parse_args()

    if not BGG_API_KEY:
        print("Error: BGG_API_KEY is not configured in .env", file=sys.stderr)
        sys.exit(1)

    if args.ids:
        game_ids = args.ids
    elif args.csv.exists():
        game_ids = load_game_ids_from_csv(args.csv, limit=args.limit, include_defaults=True)
    else:
        print(f"Error: {args.csv} not found. Download it from BGG Data Dumps or pass --ids.", file=sys.stderr)
        sys.exit(1)

    print(f"Preparing to fetch {len(game_ids)} unique games (batch size {BATCH_SIZE}, delay {REQUEST_DELAY_SEC}s)...")
    items = fetch_all_games(game_ids)

    print(f"Generating ABox Turtle for {len(items)} games...")
    turtle_output = generate_turtle(items)
    args.abox.write_text(turtle_output, encoding="utf-8")
    print(f"Saved ABox to {args.abox}.")

    merge_ontology(args.tbox, args.abox, args.output)


if __name__ == "__main__":
    main()