# Godspeed Retail Intelligence Dashboard

Godspeed streetwear retail intelligence system. Built with Flask + Google Sheets.

## Deploy on Render
- **Type:** Web Service
- **Build Command:** `pip install -r requirements.txt`
- **Start Command:** `gunicorn app:app`
- **Environment:** Python 3

## Google Sheets Integration (Optional)
Without credentials, the dashboard loads but shows empty data.
To enable live data, set these environment variables in Render:
- `GOOGLE_TOKEN_JSON` — contents of your drive-token.json
- `GOOGLE_CREDENTIALS_JSON` — contents of your google-credentials.json
