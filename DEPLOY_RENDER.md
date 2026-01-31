# Render Deployment Guide

## Prerequisites

1. Create a free account at https://render.com
2. Have your Notion integration token and database ID ready
3. Have your Google Calendar credentials.json file

## Deployment Steps

### 1. Push to GitHub

```bash
git init
git add .
git commit -m "Initial commit for Render deployment"
git branch -M main
git remote add origin https://github.com/yourusername/your-repo-name.git
git push -u origin main
```

### 2. Create Render Web Service

1. Go to https://dashboard.render.com
2. Click "New+" → "Web Service"
3. Connect your GitHub repository
4. Configure settings:
   - Name: notion-calendar-api
   - Region: Choose closest to you
   - Branch: main
   - Root Directory: Leave empty
   - Runtime: Python 3
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `uvicorn main:app --host 0.0.0.0 --port $PORT`

### 3. Set Environment Variables

In Render dashboard, add these environment variables:

```
NOTION_TOKEN=your_notion_integration_token_here
DATABASE_ID=your_notion_database_id_here
GOOGLE_CALENDAR_ID=primary
GOOGLE_CREDENTIALS_FILE=credentials.json
GOOGLE_TOKEN_FILE=token.json
```

### 4. Upload Google Credentials

1. In Render, go to your service → "Files" section
2. Upload your `credentials.json` file

### 5. Deploy

Click "Create Web Service" and wait for deployment to complete.

## Access Your API

- API URL: https://your-service-name.onrender.com
- Documentation: https://your-service-name.onrender.com/docs
- Health check: https://your-service-name.onrender.com/health

## Notes

- First deployment may take 5-10 minutes
- Render's free tier sleeps after 15 minutes of inactivity
- The service will wake up automatically when accessed
