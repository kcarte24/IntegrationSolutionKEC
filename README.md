# IntegrationSolutionKEC
emr-integration-prototype

This web app simulates an EMR integration system where patient messages are ingested, processed, transformed, and monitored through a web-based dashboard.

## Available Features:
- Message Ingestion (Both manual and automated)
- Realtime processing workflow (simulated)
- Data transformation between EMRs
- Dashboard monitoring with filtering
- Retry and deletion logic
- SQLite database with CRUD operations

## Instructions to access
1. Install dependencies: pip install flask faker
2. Run the application: python app.py
3. From the terminal, open http link to access web app: http://127.0.0.1:5000/

## Note: The db is created automatically upon startup of the app. Messages are also auto generated.
