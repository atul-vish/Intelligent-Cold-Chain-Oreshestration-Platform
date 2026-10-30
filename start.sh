bash
#!/bin/bash
set -e

echo "Starting Nivara backend..."

# Copy the read-only Render secret into a writable location
cp /etc/secrets/ec2-key.pem /tmp/ec2-key.pem
chmod 600 /tmp/ec2-key.pem

echo "SSH key prepared."

# Establish SSH tunnel to EC2 SQL Server
ssh -fN \
    -i /tmp/ec2-key.pem \
    -L 127.0.0.1:1433:127.0.0.1:1433 \
    -o BatchMode=yes \
    -o IdentitiesOnly=yes \
    -o ExitOnForwardFailure=yes \
    -o ServerAliveInterval=30 \
    -o ServerAliveCountMax=3 \
    -o StrictHostKeyChecking=yes \
    -o UserKnownHostsFile=/etc/secrets/known_hosts \
    ubuntu@13.126.137.6

echo "SSH tunnel established successfully."

# Start FastAPI
echo "Starting FastAPI server..."

exec uvicorn src.ui:app --host 0.0.0.0 --port "${PORT:-10000}"
