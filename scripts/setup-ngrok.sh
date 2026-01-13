#!/bin/bash
# =============================================================================
# PubMed Search MCP - ngrok Setup Script
# =============================================================================
# 
# This script helps you set up ngrok with a custom domain for Microsoft 
# Copilot Studio integration.
#
# Prerequisites:
#   - ngrok account (free or paid)
#   - ngrok authtoken
#   - (Paid) Custom domain configured in ngrok dashboard
#
# Usage:
#   ./scripts/setup-ngrok.sh              # Interactive setup
#   ./scripts/setup-ngrok.sh --status     # Check current status
#   ./scripts/setup-ngrok.sh --start      # Start ngrok tunnel
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
NGROK_CONFIG_FILE="$PROJECT_DIR/.ngrok.env"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_header() {
    echo ""
    echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
    echo ""
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

print_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

# Check if ngrok is installed
check_ngrok() {
    if ! command -v ngrok &> /dev/null; then
        print_error "ngrok is not installed"
        echo ""
        echo "Install ngrok:"
        echo "  # Linux (apt)"
        echo "  curl -s https://ngrok-agent.s3.amazonaws.com/ngrok.asc | sudo tee /etc/apt/trusted.gpg.d/ngrok.asc >/dev/null"
        echo "  echo 'deb https://ngrok-agent.s3.amazonaws.com buster main' | sudo tee /etc/apt/sources.list.d/ngrok.list"
        echo "  sudo apt update && sudo apt install ngrok"
        echo ""
        echo "  # macOS"
        echo "  brew install ngrok"
        echo ""
        exit 1
    fi
    print_success "ngrok is installed ($(ngrok version 2>/dev/null | head -1))"
}

# Check ngrok authentication
check_auth() {
    if ngrok config check 2>&1 | grep -q "valid"; then
        print_success "ngrok is authenticated"
        return 0
    else
        print_warning "ngrok is not authenticated"
        return 1
    fi
}

# Setup ngrok authtoken
setup_authtoken() {
    echo ""
    echo "To get your authtoken:"
    echo "  1. Go to https://dashboard.ngrok.com/get-started/your-authtoken"
    echo "  2. Copy your authtoken"
    echo ""
    read -p "Enter your ngrok authtoken: " authtoken
    
    if [ -n "$authtoken" ]; then
        ngrok config add-authtoken "$authtoken"
        print_success "Authtoken configured"
    else
        print_error "No authtoken provided"
        exit 1
    fi
}

# Get custom domain from user or config
get_domain() {
    # Check if we have a saved domain
    if [ -f "$NGROK_CONFIG_FILE" ]; then
        source "$NGROK_CONFIG_FILE"
        if [ -n "$NGROK_DOMAIN" ]; then
            echo "$NGROK_DOMAIN"
            return
        fi
    fi
    echo ""
}

# Save domain to config
save_domain() {
    local domain=$1
    echo "NGROK_DOMAIN=$domain" > "$NGROK_CONFIG_FILE"
    print_success "Domain saved to $NGROK_CONFIG_FILE"
}

# Setup custom domain
setup_domain() {
    print_header "Setup Custom Domain"
    
    echo "Your ngrok domains are listed at:"
    echo "  https://dashboard.ngrok.com/domains"
    echo ""
    echo "For paid accounts, you can:"
    echo "  - Use free dev domain (e.g., your-name.ngrok-free.app)"
    echo "  - Create custom domain (e.g., pubmed-mcp.ngrok.io)"
    echo "  - Bring your own domain (e.g., mcp.yourdomain.com)"
    echo ""
    
    current_domain=$(get_domain)
    if [ -n "$current_domain" ]; then
        echo "Current configured domain: $current_domain"
        read -p "Use this domain? (Y/n): " use_current
        if [ "$use_current" != "n" ] && [ "$use_current" != "N" ]; then
            echo "$current_domain"
            return
        fi
    fi
    
    read -p "Enter your ngrok domain (e.g., pubmed-mcp.ngrok.io): " domain
    
    if [ -n "$domain" ]; then
        save_domain "$domain"
        echo "$domain"
    else
        print_error "No domain provided"
        exit 1
    fi
}

# Start ngrok tunnel with domain
start_tunnel() {
    local domain=$1
    local port=${2:-8765}
    
    print_header "Starting ngrok Tunnel"
    
    echo "Domain: $domain"
    echo "Local port: $port"
    echo ""
    
    # Start the MCP server in background
    print_info "Starting PubMed Search MCP Server..."
    cd "$PROJECT_DIR"
    
    if [ -f ".venv/bin/activate" ]; then
        source .venv/bin/activate
    fi
    
    python run_server.py --transport streamable-http --port $port &
    SERVER_PID=$!
    sleep 2
    
    if ! kill -0 $SERVER_PID 2>/dev/null; then
        print_error "Failed to start MCP server"
        exit 1
    fi
    print_success "MCP server started (PID: $SERVER_PID)"
    
    # Start ngrok with domain
    print_info "Starting ngrok tunnel..."
    ngrok http --domain="$domain" $port &
    NGROK_PID=$!
    sleep 3
    
    if ! kill -0 $NGROK_PID 2>/dev/null; then
        print_error "Failed to start ngrok tunnel"
        kill $SERVER_PID 2>/dev/null
        exit 1
    fi
    
    print_header "🎉 Ready for Microsoft Copilot Studio!"
    
    echo ""
    echo "Your MCP server is now accessible at:"
    echo ""
    echo -e "  ${GREEN}https://${domain}/mcp${NC}"
    echo ""
    echo "═══════════════════════════════════════════════════════════════"
    echo ""
    echo "Copilot Studio Configuration:"
    echo "  Server name:        PubMed Search"
    echo "  Server URL:         https://${domain}/mcp"
    echo "  Authentication:     None"
    echo ""
    echo "═══════════════════════════════════════════════════════════════"
    echo ""
    echo "Quick test:"
    echo "  curl -X POST https://${domain}/mcp"
    echo ""
    echo "ngrok dashboard: http://localhost:4040"
    echo ""
    echo "Press Ctrl+C to stop"
    echo ""
    
    # Handle shutdown
    trap "echo ''; echo 'Shutting down...'; kill $SERVER_PID $NGROK_PID 2>/dev/null; exit 0" SIGINT SIGTERM
    
    # Wait
    wait
}

# Show status
show_status() {
    print_header "ngrok Status"
    
    check_ngrok
    
    if check_auth; then
        echo ""
        # Try to get account info
        ngrok config check 2>&1 || true
    fi
    
    domain=$(get_domain)
    if [ -n "$domain" ]; then
        echo ""
        print_info "Configured domain: $domain"
        print_info "Copilot Studio URL: https://${domain}/mcp"
    fi
    
    # Check if tunnel is running
    if curl -s http://localhost:4040/api/tunnels > /dev/null 2>&1; then
        echo ""
        print_success "ngrok tunnel is running"
        curl -s http://localhost:4040/api/tunnels | python3 -c "
import sys, json
data = json.load(sys.stdin)
for tunnel in data.get('tunnels', []):
    print(f\"  {tunnel.get('public_url')} -> {tunnel.get('config', {}).get('addr')}\")" 2>/dev/null || true
    else
        print_warning "No ngrok tunnel currently running"
    fi
}

# Main
main() {
    case "${1:-}" in
        --status)
            show_status
            ;;
        --start)
            domain=$(get_domain)
            if [ -z "$domain" ]; then
                domain=$(setup_domain)
            fi
            start_tunnel "$domain" "${2:-8765}"
            ;;
        --help|-h)
            echo "Usage: $0 [OPTION]"
            echo ""
            echo "Options:"
            echo "  --status    Show ngrok status and configuration"
            echo "  --start     Start ngrok tunnel (requires domain setup)"
            echo "  --help      Show this help message"
            echo ""
            echo "Interactive setup (no options):"
            echo "  $0"
            ;;
        *)
            print_header "PubMed Search MCP - ngrok Setup"
            
            # Step 1: Check ngrok
            check_ngrok
            
            # Step 2: Check/setup auth
            if ! check_auth; then
                setup_authtoken
            fi
            
            # Step 3: Setup domain
            domain=$(setup_domain)
            
            # Step 4: Ask to start
            echo ""
            read -p "Start ngrok tunnel now? (Y/n): " start_now
            if [ "$start_now" != "n" ] && [ "$start_now" != "N" ]; then
                start_tunnel "$domain"
            else
                echo ""
                print_info "To start later, run:"
                echo "  ./scripts/setup-ngrok.sh --start"
            fi
            ;;
    esac
}

main "$@"
