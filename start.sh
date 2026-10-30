#!/bin/bash
set -Eeuo pipefail

echo "Starting Nivara backend..."

# Verify required SSH files

SSH_KEY="/etc/secrets/ec2-key.pem"
KNOWN_HOSTS="/etc/secrets/known_hosts"

if [[ ! -f "$SSH_KEY" ]]; then
echo "ERROR: SSH private key not found: $SSH_KEY"
exit 1
fi

if [[ ! -f "$KNOWN_HOSTS" ]]; then
echo "ERROR: SSH known_hosts file not found: $KNOWN_HOSTS"
exit 1
fi

# Secure SSH private key permissions

chmod 600 "$SSH_KEY"

# Start SSH tunnel to EC2 SQL Server

echo "Establishing SSH tunnel..."

ssh -fN 
-i "$SSH_KEY" 
-L 127.0.0.1:1433:127.0.0.1:1433 
-o BatchMode=yes 
-o ConnectTimeout=20 
-o ExitOnForwardFailure=yes 
-o ServerAliveInterval=30 
-o ServerAliveCountMax=3 
-o StrictHostKeyChecking=yes 
-o UserKnownHostsFile="$KNOWN_HOSTS" 
ubuntu@13.126.137.6

echo "SSH tunnel established successfully."

# Start FastAPI

echo "Starting FastAPI server..."

exec uvicorn src.ui:app 
--host 0.0.0.0 
--port "${PORT:-10000}"
