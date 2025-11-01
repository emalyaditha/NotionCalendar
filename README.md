# Notion Google Calendar Sync API

This API syncs your Notion database projects with Google Calendar. When projects are added, updated, or deleted in Notion, the changes are automatically reflected in Google Calendar.

## 🚀 Quick Start

### Prerequisites

1. Python 3.7+
2. Google Account with Calendar access
3. Notion API token and Database ID

### Installation

```bash
# Install dependencies
pip install -r requirements.txt

# Create .env file with your tokens (see Configuration section)
# Copy .env.example if you have one

# Run the server
python main.py
```

### Access Endpoints

- API Docs: http://localhost:8000/docs
- Get Data: http://localhost:8000/get-data
- Sync Calendar: http://localhost:8000/sync-calendar (POST)
- Health: http://localhost:8000/health

## 🔧 Configuration

### 1. Environment Variables (in `.env` file)

```
NOTION_TOKEN=your_notion_api_token_here
DATABASE_ID=your_notion_database_id_here
GOOGLE_CALENDAR_ID=primary
GOOGLE_CREDENTIALS_FILE=credentials.json
GOOGLE_TOKEN_FILE=token.json
```

### 2. Google Calendar API Setup

1. **Create a Google Cloud Project:**

   - Go to [Google Cloud Console](https://console.cloud.google.com/)
   - Create a new project or select an existing one

2. **Enable Google Calendar API:**

   - Navigate to "APIs & Services" > "Library"
   - Search for "Google Calendar API"
   - Click "Enable"

3. **Create OAuth 2.0 Credentials:**

   - Go to "APIs & Services" > "Credentials"
   - Click "Create Credentials" > "OAuth client ID"
   - Choose "Desktop app" as application type
   - Give it a name (e.g., "Notion Calendar Sync")
   - Click "Create"

4. **Download Credentials:**

   - Click the download icon next to your newly created OAuth 2.0 client ID
   - Save the JSON file as `credentials.json` in your project directory

5. **Configure OAuth Consent Screen:**
   - Go to "APIs & Services" > "OAuth consent screen"
   - Choose "External" (unless you're using a Google Workspace account)
   - Fill in required fields and click "Save and Continue"
   - Add the scope: `https://www.googleapis.com/auth/calendar`
   - Add yourself as a test user or publish the app

## 📁 Critical Files

### Required Files

1. **`.env` file** - Contains all your sensitive API keys (DO NOT commit to Git!)
2. **`credentials.json`** - Downloaded from Google Cloud Console (DO NOT commit to Git!)
3. **`main.py`** - Main application file with all API endpoints
4. **`requirements.txt`** - Python dependencies

### Auto-generated Files

1. **`sync_mapping.json`** - Maps Notion page IDs to Google Calendar event IDs (OK to commit)
2. **`token.json`** - Google OAuth authentication token (DO NOT commit to Git!)

## 🎯 Usage

### Sync Endpoint

```bash
POST http://localhost:8000/sync-calendar
```

This endpoint:

- ✅ Creates new calendar events for new projects in Notion
- ✅ Updates existing calendar events when projects change
- ✅ Deletes calendar events for projects removed from Notion
- ✅ Skips projects without start dates

### Response Example:

```json
{
  "status": "success",
  "created": 5,
  "updated": 2,
  "deleted": 1,
  "skipped": 0,
  "total_notion_items": 7,
  "total_synced": 6
}
```

## 🔧 How It Works

1. **Tracking:** The system maintains a `sync_mapping.json` file that maps Notion page IDs to Google Calendar event IDs
2. **Change Detection:** Uses hash comparison to detect changes in project data
3. **Event Mapping:**
   - **Project Name** → Calendar Event Title
   - **Start Date** → Event Start Date
   - **End Date** → Event End Date (if provided)
   - **Customer Name, Status, Task Type, Tasks Tracker** → Event Description

## ⚠️ Security Important

### Files to NEVER Commit to Git:

- ❌ `.env` - Contains API tokens
- ❌ `credentials.json` - OAuth credentials
- ❌ `token.json` - Authentication tokens
- ✅ `sync_mapping.json` - OK to commit (no sensitive data)

## ⚠️ Common Issues & Fixes

### 403 Access Denied Error

**Problem:** You're seeing "Notion Task has not completed the Google verification process" or "Error 403: access_denied"

**Quick Fix Options:**

1. **Add Yourself as Test User (Quickest):**

   - Go to Google Cloud Console → APIs & Services → OAuth consent screen
   - Scroll down to "Test users" section → Click "+ ADD USERS"
   - Enter your Google email address → Click "ADD" → Click "SAVE"

2. **Publish Your App (Recommended):**
   - In OAuth Consent Screen, scroll to "Publishing status" section
   - Click "PUBLISH APP" button → Confirm

### Other Common Issues

1. **Missing `.env` file:**

   - Error: "NOTION_TOKEN environment variable is required"
   - Fix: Create `.env` file with your tokens

2. **Missing `credentials.json`:**

   - Error: "Google credentials file not found"
   - Fix: Download from Google Cloud Console

3. **405 Method Not Allowed:**

   - Error: "Method Not Allowed"
   - Fix: Use POST method for `/sync-calendar`

4. **Token expired:**
   - Delete `token.json` and run sync again to re-authenticate

## 🎯 Next Steps

1. ✅ Ensure `.env` file exists with your tokens
2. ✅ Ensure `credentials.json` is in project folder
3. ✅ Run `python main.py`
4. ✅ Visit http://localhost:8000/docs
5. ✅ Test sync with POST to `/sync-calendar`

## 🚀 Deployment

This application can be deployed to several free hosting platforms:

### Render (Recommended)

1. Fork this repository to your GitHub account
2. Go to [Render](https://render.com/) and create an account
3. Click "New" → "Web Service"
4. Connect your GitHub repository
5. Set the following:
   - Name: `notion-google-calendar-sync`
   - Runtime: `Python 3`
   - Build command: `pip install -r requirements.txt`
   - Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
6. Add environment variables in the "Environment Variables" section
7. Click "Create Web Service"

### Railway

1. Fork this repository to your GitHub account
2. Go to [Railway](https://railway.app/) and create an account
3. Click "New Project" → "Deploy from GitHub repo"
4. Select your repository
5. Railway will auto-detect the Python project
6. Add environment variables in the "Variables" section
7. Deploy the application

### Heroku

1. Fork this repository to your GitHub account
2. Install [Heroku CLI](https://devcenter.heroku.com/articles/heroku-cli)
3. Login to Heroku CLI: `heroku login`
4. Create a new app: `heroku create your-app-name`
5. Set buildpack: `heroku buildpacks:set heroku/python`
6. Deploy: `git push heroku main`
7. Set environment variables: `heroku config:set KEY=VALUE`

### Environment Variables for Deployment

You'll need to set these environment variables in your hosting platform:

```
NOTION_TOKEN=your_notion_api_token_here
DATABASE_ID=your_notion_database_id_here
GOOGLE_CALENDAR_ID=primary
GOOGLE_CREDENTIALS_FILE=credentials.json
GOOGLE_TOKEN_FILE=token.json
```

Note: For Google OAuth to work on deployed applications, you'll need to update the OAuth redirect URIs in the Google Cloud Console to match your deployed application's URL.
