#!/bin/bash
#
# Setup Railway PR Preview Environment with PostgreSQL
#
# This script creates a new Railway environment with a PostgreSQL database
# and configures the app service to use it.
#
# Usage:
#   ./scripts/setup-railway-env.sh <environment-name>
#
# Example:
#   ./scripts/setup-railway-env.sh pr-123
#
# Prerequisites:
#   - Railway CLI installed (https://railway.app/cli)
#   - RAILWAY_TOKEN environment variable set
#   - Linked to a Railway project (railway link)

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check prerequisites
check_prerequisites() {
    if ! command -v railway &> /dev/null; then
        log_error "Railway CLI not found. Install it with: curl -fsSL https://railway.app/install.sh | sh"
        exit 1
    fi

    if [ -z "$RAILWAY_TOKEN" ]; then
        log_warn "RAILWAY_TOKEN not set. You may need to authenticate interactively."
    fi
}

# Parse arguments
ENV_NAME="${1:-}"

if [ -z "$ENV_NAME" ]; then
    log_error "Environment name is required"
    echo "Usage: $0 <environment-name>"
    echo "Example: $0 pr-123"
    exit 1
fi

log_info "Setting up Railway environment: $ENV_NAME"

check_prerequisites

# Create or switch to the environment
log_info "Creating/switching to environment: $ENV_NAME"
if railway environment list 2>/dev/null | grep -qw "$ENV_NAME"; then
    log_info "Environment $ENV_NAME already exists, switching to it"
    railway environment "$ENV_NAME"
else
    log_info "Creating new environment: $ENV_NAME"
    railway environment create "$ENV_NAME"
    railway environment "$ENV_NAME"
fi

# Check if PostgreSQL service exists
log_info "Checking for PostgreSQL service..."
POSTGRES_EXISTS=$(railway service list 2>/dev/null | grep -i postgres || true)

if [ -z "$POSTGRES_EXISTS" ]; then
    log_info "PostgreSQL not found, provisioning new database..."

    # Add PostgreSQL plugin
    railway add --plugin postgresql

    log_info "PostgreSQL provisioned. Waiting for it to be ready..."

    # Wait for PostgreSQL to initialize
    MAX_RETRIES=30
    RETRY_COUNT=0

    while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
        # Try to get the DATABASE_URL
        DB_URL=$(railway variables get DATABASE_URL 2>/dev/null || true)

        if [ -n "$DB_URL" ]; then
            log_info "PostgreSQL is ready!"
            break
        fi

        RETRY_COUNT=$((RETRY_COUNT + 1))
        log_info "Waiting for PostgreSQL... ($RETRY_COUNT/$MAX_RETRIES)"
        sleep 5
    done

    if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
        log_warn "PostgreSQL may still be initializing. Check Railway dashboard."
    fi
else
    log_info "PostgreSQL already exists in this environment"
fi

# Deploy the application
log_info "Deploying application..."
railway up --detach

# Get deployment info
log_info "Getting deployment information..."
DEPLOY_INFO=$(railway status 2>/dev/null || echo "Status unavailable")
echo "$DEPLOY_INFO"

# Get the DATABASE_URL (masked)
DB_URL=$(railway variables get DATABASE_URL 2>/dev/null || true)
if [ -n "$DB_URL" ]; then
    # Mask the password in the URL for display
    MASKED_URL=$(echo "$DB_URL" | sed 's/:[^:@]*@/:****@/')
    log_info "DATABASE_URL is configured: $MASKED_URL"
else
    log_warn "DATABASE_URL not yet available. It will be set once PostgreSQL is fully provisioned."
fi

log_info "Environment setup complete!"
echo ""
echo "Next steps:"
echo "  1. Set required environment variables in Railway dashboard:"
echo "     - ANTHROPIC_API_KEY (required)"
echo "     - OPENAI_API_KEY (optional, for Whisper)"
echo "     - DEEPGRAM_API_KEY (optional, for Deepgram)"
echo "  2. Check deployment status: railway status"
echo "  3. View logs: railway logs"
echo ""
