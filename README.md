# Board Game Matchmaking Ontology (BGO)

An OWL/RDF ontology (`http://example.org/bgo#`) and reproducible knowledge graph pipeline for tabletop board game matchmaking, populated from BoardGameGeek (BGG) Top-200 ranked games.

## Architecture Overview

The knowledge graph separates schema and instance data following the **Ontology Development 101** methodology:

- **TBox (`tbox.ttl`)**: 11 classes under `schema:Thing`, reusing standard vocabularies (**Schema.org** and **Dublin Core Elements**), enriched with `rdfs:domain`/`rdfs:range`, `owl:disjointWith` (`bgo:CooperativeGame` vs. `bgo:CompetitiveGame`), `owl:AllDisjointClasses`, and qualified cardinality restrictions on `bgo:BoardGame`.
- **N-ary Modeling with Blank Nodes**:
  - `bgo:PlayerConfiguration` groups strict box limits (`bgo:minPlayers`, `bgo:maxPlayers`) together with BGG community poll verdicts (`bgo:recommendedPlayers`, `bgo:bestPlayers`).
  - `bgo:PlaytimeConfiguration` pairs a specific participant count (`bgo:forPlayerCount`) with an interpolated duration (`bgo:playtimeMinutes`), preserving player-dependent scaling.
- **ABox (`abox.ttl`)**: Automatically generated via `bgg_parser.py` from the BGG XML API2 (~200+ top-ranked base games, plus associated mechanics, categories, designers, and publishers) and merged with `tbox.ttl` into `ontology.ttl`.

## Competency Questions & SPARQL Verification

| ID | Competency Question | Core Ontology Terms | SPARQL File |
| :--- | :--- | :--- | :--- |
| **CQ1** | Which cooperative board games support 5 players, take under 45 minutes for 5 players, and exclude the *Player Elimination* mechanic? | `bgo:CooperativeGame`, `bgo:PlayerConfiguration`, `bgo:PlaytimeConfiguration`, `bgo:hasMechanic` | `query1_coop_5players_under_45min.rq` |
| **CQ2** | Which competitive board games have a complexity weight above 3.0 and belong to the *Science Fiction* or *Economic* categories? | `bgo:CompetitiveGame`, `bgo:complexityWeight`, `bgo:hasCategory`, `bgo:GameCategory` | `query2_complex_competitive_genres.rq` |
| **CQ3** | Which board games support solo play (minimum 1 player) and include either *Variable Player Powers* or *Worker Placement*? | `bgo:BoardGame`, `bgo:minPlayers`, `bgo:hasMechanic`, `bgo:GameMechanic` | `query3_solo_variable_powers.rq` |
| **CQ4** | Which board games are voted best or recommended for 4 players, take at most 90 minutes with 4 players, and exclude *Player Elimination*? | `bgo:bestPlayers`, `bgo:recommendedPlayers`, `bgo:forPlayerCount`, `bgo:playtimeMinutes`, `dc:creator`, `dc:publisher` | `query4_matchmaking_4players_no_elimination.rq` |

All queries filter domain concepts by human-readable `rdfs:label` values rather than hardcoded BGG identifiers and use `GROUP BY` / `SAMPLE` / `GROUP_CONCAT` to prevent row multiplication across multi-valued properties.

## Repository Structure

```text
.
├── tbox.ttl                                        # OWL schema (classes, properties, axioms)
├── abox.ttl                                        # Auto-generated RDF instances (Top-200 BGG)
├── ontology.ttl                                    # Merged TBox + ABox ready for Protégé / rdflib
├── bgg_parser.py                                   # Rate-limited BGG API2 ETL script + merger
├── matchmaker.py                                   # Interactive CLI matchmaking tool (rdflib)
├── query1_coop_5players_under_45min.rq             # CQ1 SPARQL query
├── query2_complex_competitive_genres.rq            # CQ2 SPARQL query
├── query3_solo_variable_powers.rq                  # CQ3 SPARQL query
├── query4_matchmaking_4players_no_elimination.rq   # CQ4 SPARQL query
└── README.md
```

## Quick Start

### 1. Install Dependencies

```bash
pip install rdflib requests python-dotenv
```

### 2. Run the Matchmaker CLI (using the pre-built `ontology.ttl`)

```bash
# Interactive mode (CQ1–CQ4 + custom matchmaking filters)
python matchmaker.py

# Non-interactive batch run of all 4 Competency Questions
python matchmaker.py --run-all
```

### 3. Rebuild the ABox & Ontology from BGG (Optional)

1. Download the official rankings CSV (`boardgames_ranks.csv`) from BoardGameGeek Data Dumps and place it in the project root.
2. Create a `.env` file with your BGG API bearer token:

   ```env
   BGG_API_KEY=your_token_here
   ```

3. Run the ETL pipeline (respects BGG's 20-ID batch limit and rate-limiting delays):

   ```bash
   python bgg_parser.py --limit 200
   ```

## Consistency Validation

To verify logical consistency on the full dataset:

1. Open `ontology.ttl` in Protégé.
2. Select **Reasoner → HermiT** and click **Start reasoner**.
3. Confirm zero unsatisfiable classes (`owl:Nothing`) and zero ontology inconsistency errors.