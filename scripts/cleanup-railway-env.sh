#!/bin/bash
#
# Cleanup Railway PR Preview Environment
#
# This script deletes a Railway environment and all its services
# including the PostgreSQL database.
#
# Usage:
#   ./scripts/cleanup-railway-env.sh <environment-name>
#
# Example:
#   ./scripts/cleanup-railway-env.sh pr-123

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

# Parse arguments
ENV_NAME="${1:-}"

if [ -z "$ENV_NAME" ]; then
    log_error "Environment name is required"
    echo "Usage: $0 <environment-name>"
    echo "Example: $0 pr-123"
    exit 1
fi

# Safety check - don't delete production environments
if [ "$ENV_NAME" = "production" ] || [ "$ENV_NAME" = "prod" ] || [ "$ENV_NAME" = "main" ]; then
    log_error "Refusing to delete protected environment: $ENV_NAME"
    exit 1
fi

log_info "Cleaning up Railway environment: $ENV_NAME"

# Check if environment exists
if ! railway environment list 2>/dev/null | grep -qw "$ENV_NAME"; then
    log_warn "Environment $ENV_NAME does not exist or already deleted"
    exit 0
fi

# Confirm deletion (skip in CI)
if [ -z "$CI" ] && [ -z "$RAILWAY_TOKEN" ]; then
    read -p "Are you sure you want to delete environment '$ENV_NAME' and all its data? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        log_info "Cancelled"
        exit 0
    fi
fi

# Delete the environment
log_info "Deleting environment: $ENV_NAME"
railway environment delete "$ENV_NAME" --yes

log_info "Environment $ENV_NAME has been deleted"
log_info "All services including PostgreSQL database have been removed"
