# Codex project instructions

The user is a programming beginner. Preserve the simple Vercel architecture.

- Do not add Streamlit.
- Do not add Next.js, React, a database, Docker, or npm unless a requested feature truly requires it.
- Frontend: plain HTML/CSS/JavaScript in `public/`.
- Backend: FastAPI in `index.py`.
- Baseball data logic stays in `src/`.
- Never write required persistent files to `/var/task`; Vercel deployment files are read-only.
- Temporary cache writes must remain optional.
- Run tests after changes.
- Explain deployment errors in plain English.
