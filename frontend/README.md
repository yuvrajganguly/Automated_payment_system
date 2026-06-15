# Payout System — Frontend

React + Vite + TypeScript + Tailwind UI sitting on top of the FastAPI backend.

## Install & run

```
cd frontend
npm install
npm run dev
```

The dev server runs at <http://localhost:5173> and proxies `/api/*` to the
FastAPI server at `http://127.0.0.1:8000`. Start the backend first:

```
pip install -e ".[api]"
payout-api --reload
```

## Build for production

```
npm run build
npm run preview
```

## Tech

- React 18 + TypeScript + React Router 6
- Vite (dev server + bundler)
- Tailwind 3 for styling
- JWT auth (token in `localStorage`), single `fetch` wrapper with auth header
  and 401 handling
