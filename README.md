# Diamond Futures

Diamond Futures is a Vercel-ready MLB career simulator. Search an active player and the proprietary **CURVE Engine** runs thousands of plausible careers instead of repeating a published projection.

**Live site:** [diamond-futures.vercel.app](https://diamond-futures.vercel.app)

## What it does

- Searches current MLB players by name
- Supports hitters, pitchers, and two-way role switching
- Combines MLB season history with Baseball Savant Statcast traits
- Uses optional FanGraphs benchmarks when permitted and available
- Applies age transitions learned from 25,222 modern historical age-seasons
- Models skill, playing time, and remaining MLB career length separately
- Runs 5,000 correlated Monte Carlo career paths
- Shows 10th, 50th, and 90th percentile trajectories
- Calculates milestone odds, cliff risk, second-peak odds, and retirement range
- Finds model-selected historical twins at the same age
- Includes a four-control what-if lab and two-player Career Duel
- Displays a 2016–2024 held-out model scorecard
- Provides a synthetic offline demo and forecast CSV download

## Data

- MLB Stats API: current identities and year-by-year MLB performance
- Baseball Savant: Statcast expected performance and quality of contact
- SABR Lahman Database: historical aging and career comparison training
- Chadwick Register: MLBAM-to-FanGraphs identity mapping
- FanGraphs: optional, non-blocking benchmark only; the app respects access controls and does not depend on the feed

Generated historical assets and attribution are documented in [`data/MODEL_DATA_SOURCES.md`](data/MODEL_DATA_SOURCES.md).

`CURVE Value` is the model's own transparent, WAR-like estimate. It is not FanGraphs WAR or Baseball-Reference WAR.

## Architecture

- FastAPI backend in `index.py`
- Baseball and simulation logic in `src/`
- Plain HTML, CSS, and JavaScript in `public/`
- pandas, NumPy, and requests for data/model work
- Optional temporary caching only; no database or persistent server writes
- Vercel deployment through `vercel.json`

There is no Streamlit, React, Next.js, Docker, database, or Node build step.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn index:app --reload
```

Open `http://127.0.0.1:8000`.

## Test

```bash
python -m pytest tests -q
```

## Deploy to Vercel

Import this project into Vercel or run `vercel` from the project root. Vercel recognizes the FastAPI `app` in `index.py` as a Python Function.

The `main` branch is connected to the production Vercel project, so future pushes deploy automatically.

The generated model assets are bundled read-only with the deployment. Live-source caching uses temporary storage only when available, so a cache failure never prevents a simulation.
