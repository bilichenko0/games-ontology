import argparse
import sys
from pathlib import Path
from rdflib import Graph

CQ_FILES = [
    ("CQ1: Cooperative, 5 players, <45 min, no Player Elimination", "query1_coop_5players_under_45min.rq"),
    ("CQ2: Competitive, complexity >3.0, Sci-Fi or Economic", "query2_complex_competitive_genres.rq"),
    ("CQ3: Solo-capable, Variable Player Powers or Worker Placement", "query3_solo_variable_powers.rq"),
    ("CQ4: Best/Recommended for 4 players, <=90 min, no Player Elimination", "query4_matchmaking_4players_no_elimination.rq"),
]


def resolve_query_path(filename: str) -> Path | None:
    for candidate in (Path(filename), Path("queries") / filename):
        if candidate.exists():
            return candidate
    return None


def short_cell(val: object, max_width: int = 42) -> str:
    if val is None:
        return "-"
    text = str(val)
    if text.startswith("http://example.org/bgo#"):
        text = "bgo:" + text.split("#", 1)[1]
    if len(text) > max_width:
        return text[: max_width - 3] + "..."
    return text


def print_results(result) -> None:
    headers = [str(v) for v in result.vars]
    rows = [[short_cell(row[i]) for i in range(len(headers))] for row in result]

    if not rows:
        print("  (No matching games found.)\n")
        return

    widths = [max(len(headers[i]), *(len(r[i]) for r in rows)) for i in range(len(headers))]
    sep = "+-" + "-+-".join("-" * w for w in widths) + "-+"
    fmt = "| " + " | ".join(f"{{:<{w}}}" for w in widths) + " |"

    print(sep)
    print(fmt.format(*headers))
    print(sep)
    for r in rows:
        print(fmt.format(*r))
    print(sep)
    print(f"Total matches: {len(rows)}\n")


def run_rq_file(g: Graph, title: str, filename: str) -> None:
    path = resolve_query_path(filename)
    print(f"\n=== {title} ===")
    if path is None:
        print(f"  Error: query file '{filename}' not found.\n")
        return
    sparql = path.read_text(encoding="utf-8")
    print_results(g.query(sparql))


def prompt_int(label: str, required: bool = False) -> int | None:
    while True:
        raw = input(label).strip()
        if not raw and not required:
            return None
        if raw.isdigit() and int(raw) > 0:
            return int(raw)
        print("  Please enter a positive integer.")


def prompt_float(label: str) -> float | None:
    while True:
        raw = input(label).strip().replace(",", ".")
        if not raw:
            return None
        try:
            val = float(raw)
            if 0.0 <= val <= 5.0:
                return val
        except ValueError:
            pass
        print("  Please enter a number between 0.0 and 5.0 (or press Enter to skip).")


def run_custom_search(g: Graph) -> None:
    print("\n--- Custom Board Game Matchmaking ---")
    players = prompt_int("Number of players (required, e.g. 4): ", required=True)
    rec_only = input("Only community Best/Recommended for this player count? [y/N]: ").strip().lower() == "y"
    max_time = prompt_int("Max playtime in minutes (Enter to skip): ", required=False)

    mode = input("Game mode [coop / comp / any] (default: any): ").strip().lower()
    if mode == "coop":
        type_clause = "?game a bgo:CooperativeGame ."
    elif mode == "comp":
        type_clause = "?game a bgo:CompetitiveGame ."
    else:
        type_clause = "?game a bgo:BoardGame ."

    min_weight = prompt_float("Min complexity weight 1.0-5.0 (Enter to skip): ")
    max_weight = prompt_float("Max complexity weight 1.0-5.0 (Enter to skip): ")
    no_elim = input("Exclude Player Elimination mechanic? [y/N]: ").strip().lower() == "y"

    if rec_only:
        player_clause = f"""
        ?game bgo:hasPlayerConfig ?pConfig .
        {{ ?pConfig bgo:bestPlayers {players} . }}
        UNION
        {{ ?pConfig bgo:recommendedPlayers {players} . }}
        """
    else:
        player_clause = f"""
        ?game bgo:hasPlayerConfig ?pConfig .
        ?pConfig bgo:minPlayers ?minP ;
                 bgo:maxPlayers ?maxP .
        FILTER (?minP <= {players} && ?maxP >= {players})
        """

    if max_time is not None:
        time_clause = f"""
        ?game bgo:hasPlaytimeConfig ?tConfig .
        ?tConfig bgo:forPlayerCount {players} ;
                 bgo:playtimeMinutes ?duration .
        FILTER (?duration <= {max_time})
        """
    else:
        time_clause = f"""
        OPTIONAL {{
            ?game bgo:hasPlaytimeConfig ?tConfig .
            ?tConfig bgo:forPlayerCount {players} ;
                     bgo:playtimeMinutes ?duration .
        }}
        """

    weight_filters = []
    if min_weight is not None:
        weight_filters.append(f"FILTER (?w >= {min_weight})")
    if max_weight is not None:
        weight_filters.append(f"FILTER (?w <= {max_weight})")

    if weight_filters:
        weight_clause = "?game bgo:complexityWeight ?w .\n        " + "\n        ".join(weight_filters)
    else:
        weight_clause = "OPTIONAL { ?game bgo:complexityWeight ?w . }"

    elim_clause = ""
    if no_elim:
        elim_clause = """
        FILTER NOT EXISTS {
            ?game bgo:hasMechanic ?mech .
            ?mech rdfs:label ?mLabel .
            FILTER (STR(?mLabel) = "Player Elimination")
        }
        """

    sparql = f"""
    PREFIX bgo: <http://example.org/bgo#>
    PREFIX dc: <http://purl.org/dc/elements/1.1/>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

    SELECT (SAMPLE(?rawTitle) AS ?title)
           (MIN(?duration) AS ?minutes)
           (SAMPLE(?w) AS ?weight)
           (GROUP_CONCAT(DISTINCT ?catName; separator=", ") AS ?categories)
    WHERE {{
        {type_clause}
        {player_clause}
        {time_clause}
        {weight_clause}
        {elim_clause}
        OPTIONAL {{ ?game dc:title|rdfs:label ?rawTitle . }}
        OPTIONAL {{
            ?game bgo:hasCategory ?cat .
            ?cat rdfs:label ?catLabel .
            BIND(STR(?catLabel) AS ?catName)
        }}
    }}
    GROUP BY ?game
    ORDER BY ?minutes ?title
    LIMIT 30
    """

    print("\n=== Matching Games (up to 30) ===")
    print_results(g.query(sparql))


def main() -> None:
    parser = argparse.ArgumentParser(description="CLI matchmaking tool for the Board Game Ontology.")
    parser.add_argument("--ontology", type=Path, default=Path("ontology.ttl"), help="Path to ontology.ttl")
    parser.add_argument("--run-all", action="store_true", help="Run all 4 CQ queries non-interactively and exit.")
    args = parser.parse_args()

    if not args.ontology.exists():
        print(f"Error: '{args.ontology}' not found. Run bgg_parser.py first.", file=sys.stderr)
        sys.exit(1)

    print(f"Loading {args.ontology}...")
    g = Graph()
    g.parse(args.ontology, format="turtle")
    game_count = len(list(g.subjects(predicate=None, object=None)))
    print(f"Loaded {len(g)} RDF triples ({game_count} unique subjects).\n")

    if args.run_all:
        for title, fname in CQ_FILES:
            run_rq_file(g, title, fname)
        return

    while True:
        print("Board Game Ontology Matchmaker")
        print("  1. Run all 4 Competency Questions (CQ1-CQ4)")
        print("  2. Custom matchmaking search")
        print("  3. Run a single Competency Question")
        print("  0. Exit")
        choice = input("Select an option: ").strip()

        if choice == "1":
            for title, fname in CQ_FILES:
                run_rq_file(g, title, fname)
        elif choice == "2":
            run_custom_search(g)
        elif choice == "3":
            for idx, (title, _) in enumerate(CQ_FILES, 1):
                print(f"  {idx}. {title}")
            sub = input("Choose CQ (1-4): ").strip()
            if sub in ("1", "2", "3", "4"):
                title, fname = CQ_FILES[int(sub) - 1]
                run_rq_file(g, title, fname)
        elif choice == "0":
            break
        else:
            print("Invalid option.\n")


if __name__ == "__main__":
    main()