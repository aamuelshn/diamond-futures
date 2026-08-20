# Validation — Diamond Futures

Validated on August 20, 2026.

## Passed

- Python compilation for the API, model, data clients, and asset builders
- JavaScript syntax validation
- 15 automated Python tests
- FastAPI health, root page, JavaScript, CSS, social image, and demo endpoints
- Deterministic simulation behavior for identical assumptions
- What-if longevity response test
- Live MLB player history for an active two-way player
- Live Baseball Savant hitter and pitcher profiles
- Hitter and pitcher aging assets generated from the SABR Lahman database
- Chadwick MLBAM-to-FanGraphs identity map generation
- 2016–2024 held-out model scorecard generation
- No Streamlit, database, React, Next.js, Docker, or Node build dependency
- No required writes to the deployed application directory

## External limitation

FanGraphs currently presents an automated-access challenge to server requests. Diamond Futures does not bypass that protection. The FanGraphs benchmark is optional, clearly labeled, and never blocks a forecast; the model continues with MLB, Baseball Savant, SABR Lahman, and Chadwick data.

## Deployment status

A production Vercel deployment still requires access to the owner's Vercel account. The project itself remains Vercel-ready through `index.py`, `requirements.txt`, and `vercel.json`.
