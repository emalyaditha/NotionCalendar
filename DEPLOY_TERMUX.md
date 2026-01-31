# Termux Deployment Guide

## Prerequisites

Install Termux from F-Droid (recommended) or Google Play Store

## Setup Instructions

### 1. Install Required Packages

```bash
pkg update && pkg upgrade
pkg install python python-pip git
```

### 2. Clone or Transfer Your Project

Option A - If you have GitHub access:

```bash
git clone https://github.com/yourusername/your-repo-name.git
cd your-repo-name
```

Option B - Transfer files manually:

```bash
# Create project directory
mkdir ~/notion-api
cd ~/notion-api
# Then transfer your files using scp or other methods
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Set Up Environment Variables

Create `.env` file:

```bash
nano .env
```

Add your credentials:

```
NOTION_TOKEN=your_notion_token_here
DATABASE_ID=your_database_id_here
GOOGLE_CALENDAR_ID=primary
GOOGLE_CREDENTIALS_FILE=credentials.json
GOOGLE_TOKEN_FILE=token.json
```

### 5. Get Google Credentials

Transfer your `credentials.json` file to Termux:

```bash
# From your computer:
scp credentials.json user@phone-ip:/data/data/com.termux/files/home/notion-api/
```

### 6. Run the Application

```bash
python main.py
```

## Making It Persistent

### Option 1: Using tmux

```bash
# Install tmux
pkg install tmux

# Start session
tmux new -s notion-api

# Run your app
python main.py

# Detach: Ctrl+B, then D
# Reattach: tmux attach -t notion-api
```

### Option 2: Create a Service Script

```bash
nano ~/notion-api/run.sh
```

Add this content:

```bash
#!/bin/bash
cd ~/notion-api
source venv/bin/activate  # if using virtual environment
python main.py
```

Make it executable:

```bash
chmod +x ~/notion-api/run.sh
```

## Network Access

To access from other devices on your network:

1. Find your phone's IP: `ip addr show wlan0`
2. The API will be accessible at: `http://YOUR_PHONE_IP:8002`

## Troubleshooting

- Ensure your phone's firewall allows port 8002
- Check if Termux has storage permissions
- For Google Auth, you may need to set up port forwarding or use a public URL service like ngrok
