# SalesNexa AI

**Predict • Analyze • Grow**

SalesNexa AI is an original Flask business command center for sales, inventory, forecasting, anomaly detection, and explainable business questions. The bundled dataset is explicitly demo data and is not real company information.

## Features

- Secure Werkzeug password hashing, sessions, role checks, audit logs, and safe error pages.
- Normalized SQLite schema with foreign keys and indexes, designed around portable SQL.
- Server-calculated sales totals with an atomic inventory reduction, movement record, low-stock notification, and audit event.
- Catalog, customer, supplier, inventory, analytics, report, forecast, and anomaly service boundaries.
- Linear-regression revenue forecast with MAE, RMSE, MAPE, and an honest insufficient-history response.
- Explainable anomaly bounds and a controlled NexaBot tool system. NexaBot never accepts or generates arbitrary SQL.
- English, Telugu, Hindi, Tamil, and Kannada translation dictionaries.
- Responsive futuristic command-center UI with Chart.js and a lightweight CSS data-sphere treatment.

## Setup

Python 3.11+ is recommended.

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
$env:PYTHONPATH='.'
python database\seed.py
python app.py
```

You can also start the development server with npm:

```powershell
npm run dev
```

## Deploy

Create a GitHub repository, then from this project folder run `git init`, `git add .`, `git commit -m "Initial SalesNexa release"`, `git branch -M main`, `git remote add origin YOUR_GITHUB_REPOSITORY_URL`, and `git push -u origin main`. In Render, choose **New + > Blueprint**, connect the repository, and select `render.yaml`. Render will install the requirements, start Gunicorn, and mount persistent storage for the SQLite database. Add `AI_API_KEY` privately in Render only; never commit it.

### Vercel

Import the repository into Vercel and deploy it with the project root unchanged. Vercel detects `vercel.json` and `requirements.txt`, then serves the Flask app through `api/index.py`. Set `SECRET_KEY` and any optional AI variables in the Vercel project settings. Vercel's filesystem is ephemeral, so the default `/tmp/salesnexa.db` database is suitable only for a demo; use an external PostgreSQL-compatible database for persistent production data.

Open `http://127.0.0.1:5000`. To initialize an empty database without demo records, use `flask --app app init-db`.

## Demo accounts

All demo accounts use the clearly non-production password `DemoPass123!`:

- `admin@salesnexa.local` (ADMIN)
- `manager@salesnexa.local` (MANAGER)
- `staff@salesnexa.local` (STAFF)
- `viewer@salesnexa.local` (VIEWER)

## Architecture

`app.py` owns the factory and HTTP boundary, `db.py` owns connections, `database/schema.sql` defines relational storage, `services/` contains business calculations, `ml/` contains model logic, `chatbot/tools.py` contains the allowlisted data tools, and templates/static contain the responsive presentation layer. The schema separates sales headers and line items, inventory state and inventory movements, users and roles, and forecasts from forecast runs so a later PostgreSQL/MySQL migration is straightforward.

## Honest AI behavior

Forecasts are calculated from grouped monthly sales and report validation errors from observed residuals. Anomaly detection only reports statistical deviation and offers ordinary business explanations; it does not label activity as fraud. NexaBot routes language cues to fixed functions such as `get_total_sales`, `get_top_products`, `get_low_stock_products`, `get_profit_summary`, and `get_category_performance`. With insufficient data it says so instead of inventing an answer. `AI_API_KEY` and `AI_MODEL` are optional and never hard-coded. When configured, NexaBot sends the question and a read-only business snapshot to the OpenAI-compatible endpoint in `AI_BASE_URL`; failed or missing API calls fall back to grounded local answers. `AI_TIMEOUT` controls the request limit.

The dashboard language menu supports Indian languages including Hindi, Bengali, Telugu, Marathi, Tamil, Gujarati, Kannada, Malayalam, Punjabi, Urdu, Odia, Assamese, Sanskrit and Nepali, plus French, German, Spanish, Arabic and Japanese. Voice input and spoken answers use the browser Web Speech API and the selected locale, so microphone and speech support depends on the browser and installed voices.

## Testing

```powershell
$env:PYTHONPATH='.'
pytest -q
```

## Environment

See `.env.example` for `SECRET_KEY`, `DATABASE_PATH`, `AI_API_KEY`, `AI_MODEL`, `AI_BASE_URL`, and `AI_TIMEOUT`. In production, set a random secret, use HTTPS, and move the SQLite file to PostgreSQL/MySQL through a migration layer.
