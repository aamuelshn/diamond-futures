# Start here

Diamond Futures is already structured for Vercel and intentionally uses a simple FastAPI + plain JavaScript architecture.

**Live site:** [diamond-futures.vercel.app](https://diamond-futures.vercel.app)

## First local run

1. Activate the Python environment: `source .venv/bin/activate`
2. Install packages: `pip install -r requirements.txt`
3. Run tests: `python -m pytest tests -q`
4. Start the site: `uvicorn index:app --reload`
5. Open `http://127.0.0.1:8000`

The page opens with a synthetic sample player, so the full simulation experience works even when a live baseball source is temporarily unavailable.

## Important model language

- `CURVE Value` is an internal WAR-like value estimate, not an official WAR statistic.
- Percentile bands describe uncertainty; they are not guarantees.
- FanGraphs is optional because its automated access controls can reject server requests.
- MLB and Baseball Savant remain the live player-performance sources.

## Updating the historical model

The model ships with compact generated assets. Instructions and source attribution are in `data/MODEL_DATA_SOURCES.md`; reproducible builders are in `scripts/`.
