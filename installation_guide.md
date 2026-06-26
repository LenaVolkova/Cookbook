# Installation & Deployment Guide: Cookbook AI Agent

This guide is designed for those who copied this cookbook agent project from GitHub and want to install, configure, and deploy it to their Google Cloud Project or locally, linking it to their own Google Sheet.

---

## Prerequisites
Before you start, make sure you have the following installed on your computer:
1. **Python 3.11** (Ensure Python is added to your system's PATH).
2. **Google Cloud SDK (gcloud CLI)**: [Download and install guide](https://cloud.google.com/sdk/docs/install).
3. **Git**: [Download and install guide](https://git-scm.com/downloads).
4. A Google account to access Google Drive, Google Sheets, and Google Cloud Console.

---

## Step 1: Google Sheet Setup

1. **Create a new Google Sheet** in your Google Drive.
2. Copy the **Spreadsheet ID** from the sheet's URL. The URL format is:
   `https://docs.google.com/spreadsheets/d/SPREADSHEET_ID/edit#gid=0`
   *(Save this ID, you will need it later.)*
3. **(Optional) Add a header row**: The agent will automatically initialize the headers if the sheet is empty. If you prefer to add them manually, write these names in Row 1 (columns A to D):
   - **Column A**: `Title`
   - **Column B**: `Ingredients`
   - **Column C**: `Steps`
   - **Column D**: `Category`
   *(Note: The Timestamp column is not required. The agent will automatically append and manage timestamps as needed.)*

---

## Step 2: Google Cloud Project Setup

1. Open the [Google Cloud Console](https://console.cloud.google.com/).
2. Click the project dropdown list in the top navigation bar and select **New Project**. Name it (e.g., `my-cookbook-agent`) and click **Create**.
3. Enable the required APIs. Search for the following APIs in the search bar and click **Enable**:
   - **Vertex AI API** (`aiplatform.googleapis.com`)
   - **Cloud Build API** (`cloudbuild.googleapis.com`)
   - **Cloud Run API** (`run.googleapis.com`)
   - **Secret Manager API** (`secretmanager.googleapis.com`)

---

## Step 3: Google Service Account Key

To write recipes to your Google Sheet, the agent needs a Google Service Account key.

1. In the Google Cloud Console, navigate to **IAM & Admin** > **Service Accounts**.
2. Click **Create Service Account** at the top.
3. Fill in the service account name (e.g., `cookbook-sheets-sa`) and click **Create and Continue**.
4. Grant this service account the role of **Project** > **Editor** or **Vertex AI User** so it has permissions to make Vertex AI calls. Click **Continue**, then click **Done**.
5. Find your newly created service account in the list, click the **Three Dots** under "Actions" and select **Manage Keys**.
6. Click **Add Key** > **Create New Key**. Select **JSON** and click **Create**.
7. A JSON file will automatically download to your computer.
8. **Rename this downloaded file to `service-account.json`** and place it in the **root directory** of your copied project repository.
9. **Share your Google Sheet**:
   - Open the JSON file and locate the `"client_email"` key (e.g., `cookbook-sheets-sa@your-project-id.iam.gserviceaccount.com`).
   - Open your Google Sheet, click **Share** in the top-right corner, paste this email, grant it **Editor** permissions, and click **Share**.

---

## Step 4: Configuration Files (`.env` and `service-account.json`)

### 1. `service-account.json` Template
Your `service-account.json` file should look like this (downloaded from GCP Service Accounts):
```json
{
  "type": "service_account",
  "project_id": "YOUR_PROJECT_ID",
  "private_key_id": "YOUR_PRIVATE_KEY_ID",
  "private_key": "-----BEGIN PRIVATE KEY-----\nYOUR_PRIVATE_KEY_HERE\n-----END PRIVATE KEY-----\n",
  "client_email": "cookbook-sheets-sa@YOUR_PROJECT_ID.iam.gserviceaccount.com",
  "client_id": "YOUR_CLIENT_ID",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token",
  "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
  "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/cookbook-sheets-sa%40YOUR_PROJECT_ID.iam.gserviceaccount.com",
  "universe_domain": "googleapis.com"
}
```

### 2. `.env` Template
Create a new file named **`.env`** in the **root directory** of your repository and fill it in:
```ini
# Google Cloud Configuration
GOOGLE_CLOUD_PROJECT=YOUR_PROJECT_ID
GOOGLE_CLOUD_LOCATION=us-east1

# Reasoning Engine ID (Leave empty during the first installation. 
# Once the backend is deployed in Step 6, paste the generated ID here.)
AGENT_RUNTIME_ID=
```

---

## Step 5: Local Installation & Testing

1. Open your terminal (Mac/Linux) or Command Prompt (Windows).
2. Navigate to the project root directory:
   ```bash
   cd /path/to/cloned/repository
   ```
3. Install the `google-agents-cli` tool:
   ```bash
   uv tool install google-agents-cli
   ```
   *(If `uv` is not installed, install it via `curl -LsSf https://astral.sh/uv/install.sh | sh` or use standard Python virtualenvs: `python -m venv .venv && source .venv/bin/activate && pip install google-agents-cli`)*
4. Log in to your Google Cloud SDK:
   ```bash
   gcloud auth login
   gcloud auth application-default login
   gcloud config set project YOUR_PROJECT_ID
   ```
5. Install dependencies and run the agent playground locally to verify:
   ```bash
   agents-cli install
   agents-cli playground
   ```
   Open the printed URL in your browser to chat with the agent and verify it adds rows to your sheet.

---

## Step 6: Deploy to Google Cloud

### 1. Deploy the Backend Agent (Vertex AI)
1. Run the following command from the root directory to deploy the agent reasoning engine to Google Cloud:
   ```bash
   agents-cli deploy --project YOUR_PROJECT_ID --region us-east1
   ```
2. Once successful, the terminal will print the **Agent Runtime ID** (format: `projects/YOUR_PROJECT_ID/locations/us-east1/reasoningEngines/NUMBER`).
3. Open your `.env` file and update **`AGENT_RUNTIME_ID`** with this printed value.
4. **Share Google Sheet with the deployed Service Account**:
   - The deployment output will print a runtime service account email (format: `service-NUMBER@gcp-sa-aiplatform-re.iam.gserviceaccount.com`).
   - Copy this email, open your Google Sheet, click **Share**, and grant **Editor** access to this email as well.

### 2. Run the Frontend Dashboard Locally (Optional)

Before deploying the frontend dashboard to Google Cloud, you can run and test it locally on your computer.

1. **Verify Prerequisites**: 
   - Ensure you have deployed the backend agent in the previous step and set `AGENT_RUNTIME_ID` in your `.env` file in the root directory.
   - Verify that your local terminal is authenticated to access Vertex AI services on Google Cloud:
     ```bash
     gcloud auth application-default login
     ```
2. **Navigate to the frontend directory**:
   ```bash
   cd cookbook_frontend
   ```
3. **Install dependencies**:
   - If using **`uv`**:
     ```bash
     uv venv
     source .venv/bin/activate
     uv pip install -r requirements.txt
     ```
   - If using standard **`pip`**:
     ```bash
     python -m venv .venv
     source .venv/bin/activate
     pip install -r requirements.txt
     ```
     *(On Windows CMD, activate using `.venv\Scripts\activate.bat`. On Windows PowerShell, use `.venv\Scripts\Activate.ps1`).*
4. **Launch the FastAPI app**:
   Start the local development server using Uvicorn:
   ```bash
   uvicorn main:app --reload
   ```
   Alternatively, run it directly via python:
   ```bash
   python main.py
   ```
5. **Access the Dashboard**:
   Open your browser and navigate to **[http://localhost:8000](http://localhost:8000)**. You can now chat with your deployed agent in real-time through the frontend web interface!

### 3. Deploy the Frontend Dashboard (Cloud Run)
1. Ensure your root-level `Dockerfile` is present.
2. Deploy the FastAPI frontend directly to Cloud Run:
   ```bash
   gcloud run deploy cookbook-dashboard \
     --source . \
     --region us-east1 \
     --allow-unauthenticated \
     --set-env-vars GOOGLE_CLOUD_PROJECT=YOUR_PROJECT_ID,AGENT_RUNTIME_ID=YOUR_DEPLOYED_AGENT_RUNTIME_ID
   ```
3. The command will complete and print a **Service URL** (format: `https://cookbook-dashboard-XXXXX.run.app`).
4. Click the URL to open your cookbook agent manager dashboard, live on the internet!
