# CURVE Engine data sources

The generated model assets in this folder use the 2025 edition of the SABR
Lahman Baseball Database, created by Sean Lahman and maintained by SABR. The
source database covers MLB history through 2025 and is distributed under the
Creative Commons Attribution-ShareAlike 3.0 license.

`aging_priors.json` and `historical_comps.json.gz` are therefore made available
under CC BY-SA 3.0. The application source code remains covered by the root
project license.

- Official source: https://sabr.org/lahman-database
- Training window used here: 1980–2025
- Generated assets: `aging_priors.json` and `historical_comps.json.gz`
- Rebuild script: `scripts/build_aging_assets.py`

The `player_id_map.csv.gz` file is generated from the Chadwick Bureau Persons
Register, distributed under the Open Data Commons Attribution License. It maps
MLBAM identifiers to FanGraphs identifiers without matching players by name.

- Source: https://github.com/chadwickbureau/register
- Rebuild script: `scripts/build_player_id_map.py`

Live player identity and season history come from MLB's public Stats API.
Statcast quality-of-contact metrics come from Baseball Savant's public custom
leaderboard CSV. FanGraphs is an optional, non-blocking reference feed: the
application never attempts to bypass its access controls and continues without
it when automated access is unavailable.
