#!/bin/bash
# deploy.sh — One-command Railway deployment
# Run this once from your project root after installing the Railway CLI.
# https://docs.railway.app/develop/cli

set -e

echo "🚂 Deploying Namma BLR News Tracker to Railway..."

# 1. Check Railway CLI is installed
if ! command -v railway &> /dev/null; then
  echo "❌ Railway CLI not found. Install it first:"
  echo "   npm install -g @railway/cli"
  echo "   then: railway login"
  exit 1
fi

# 2. Login check
railway whoami || railway login

# 3. Create project (skip if already linked)
if [ ! -f ".railway/config.json" ]; then
  echo "📦 Creating new Railway project..."
  railway init --name "namma-blr-news"
fi

# 4. Set required environment variables
echo "🔑 Setting environment variables..."
railway variables set ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:?Need ANTHROPIC_API_KEY in shell env}"
railway variables set RUN_ON_STARTUP=true
railway variables set PYTHONUNBUFFERED=1

# Optional: NewsAPI key
if [ -n "$NEWSAPI_KEY" ]; then
  railway variables set NEWSAPI_KEY="$NEWSAPI_KEY"
fi

# 5. Add a Volume for SQLite persistence
echo "💾 Adding persistent volume for database..."
echo "   → In the Railway dashboard: Service → Volumes → Add Volume"
echo "   → Mount path: /data"
echo "   → Set env var: RAILWAY_VOLUME_MOUNT_PATH=/data"
echo "   (Railway CLI volume creation requires the dashboard for now)"
echo ""

# 6. Deploy
echo "🚀 Deploying..."
railway up --detach

echo ""
echo "✅ Deploy kicked off!"
echo ""
echo "Next steps:"
echo "  1. Open Railway dashboard and add a Volume mounted at /data"
echo "  2. Add RAILWAY_VOLUME_MOUNT_PATH=/data in Variables"
echo "  3. railway logs --tail   ← watch startup scrape"
echo "  4. railway open          ← get your public URL"
echo ""
echo "API will be live at: https://<your-app>.up.railway.app"
echo "Health check:        https://<your-app>.up.railway.app/health"
echo "Feed endpoint:       https://<your-app>.up.railway.app/api/articles"
