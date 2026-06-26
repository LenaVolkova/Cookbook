# Cookbook AI Agent Manager Dashboard

A standalone FastAPI web application serving as a responsive, interactive chat dashboard interface for the Cookbook AI Agent deployed on Google Cloud.

## Features
- **Tailwind CSS Styling**: Modern, dark-themed, glassmorphism chat UI.
- **Markdown Support**: Clean rendering of recipe lists, instructions, and bold text using `marked.js`.
- **GCP Session Persistence**: Automatically maps client sessions to GCP Reasoning Engine sessions.
- **Interruption Support**: Seamless handling of Human-in-the-Loop inputs for "save-recipe" slot-filling and "recipe-recommend" confirmation loops.
- **Robust Error Handling**: Connection/auth issues are caught and returned as friendly notices in the chat history.

---

## Setup Instructions

### 1. Prerequisites
- **Python**: Version 3.11 or later.
- **GCP gcloud CLI**: Installed and configured.

### 2. Google Cloud Authentication Credentials
You must authenticate your local environment to access your deployed Vertex AI Reasoning Engine:

#### Option A: Authenticate using your user credentials (Recommended)
Run the following command to login and generate Application Default Credentials (ADC) for Vertex AI client calls:
```bash
gcloud auth application-default login
```

#### Option B: Authenticate using a Service Account JSON
If you have a Service Account key (e.g. `service-account.json` in the project root):
1. Copy or refer to your JSON file.
2. Set the `GOOGLE_APPLICATION_CREDENTIALS` environment variable pointing to the absolute path of the JSON key:
   - **Linux/macOS**:
     ```bash
     export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account.json"
     ```
   - **Windows (CMD)**:
     ```cmd
     set GOOGLE_APPLICATION_CREDENTIALS="C:\path\to\service-account.json"
     ```
   - **Windows (PowerShell)**:
     ```powershell
     $env:GOOGLE_APPLICATION_CREDENTIALS="C:\path\to\service-account.json"
     ```

### 3. Environment Variables
The application needs your **GCP Project ID** and the **Reasoning Engine ID** to route queries.

Set the following environment variables (or let `main.py` discover them from `.env` or `deployment_metadata.json` in the root workspace):
- `GOOGLE_CLOUD_PROJECT`: Your Google Cloud Project ID.
- `AGENT_RUNTIME_ID`: The full resource ID of your deployed reasoning engine (e.g., `projects/1014767188020/locations/us-east1/reasoningEngines/5555084587245240320` or just the numeric ID `5555084587245240320`).
- `GOOGLE_CLOUD_LOCATION`: The location region (defaults to `us-east1` if using a numeric ID).

---

## Installation & Execution

### 1. Install dependencies
Run `uv` or `pip` to install dependencies:

Using `uv`:
```bash
uv pip install -r requirements.txt
```

Using `pip`:
```bash
pip install -r requirements.txt
```

### 2. Start the FastAPI application
Run `uvicorn` to start the development server:
```bash
uvicorn main:app --reload
```
Alternatively, execute it with python directly:
```bash
python main.py
```

Open your browser and navigate to:
**[http://localhost:8000](http://localhost:8000)**

You can now interact with your deployed agent in real-time!
