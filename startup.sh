#!/bin/bash
# Simplified startup script for CalDAV Web Client
# Session-only storage, no database required

set -e

echo "Starting CalDAV Web Client..."

# Set default environment variables
export FLASK_ENV=${FLASK_ENV:-production}
export PORT=${PORT:-5000}
export LOG_LEVEL=${LOG_LEVEL:-info}

# Detect if we're running as root and can change permissions
if [ "$(id -u)" = "0" ]; then
    echo "Running as root - checking mounted volume permissions..."
    
    # Check if /app/data is mounted and get its ownership
    if [ -d "/app/data" ]; then
        DATA_UID=$(stat -c "%u" /app/data)
        DATA_GID=$(stat -c "%g" /app/data)
        echo "Mounted data directory owned by UID:GID $DATA_UID:$DATA_GID"
        
        # Create app user with matching UID/GID to the mounted volume
        if ! id -u app >/dev/null 2>&1; then
            echo "Creating app user with UID:GID $DATA_UID:$DATA_GID"
            groupadd -g $DATA_GID app 2>/dev/null || true
            useradd -u $DATA_UID -g $DATA_GID -d /home/app -m -s /bin/bash app 2>/dev/null || true
        fi
        
        # Ensure data directory is writable (for potential log files or future use)
        chown -R app:app /app/data
        chmod 755 /app/data
        
        # Switch to app user and re-exec this script
        echo "Switching to app user..."
        exec su app -c "exec $0"
    else
        echo "No data directory mounted, creating app user with default UID"
        useradd -u 1000 -d /home/app -m -s /bin/bash app 2>/dev/null || true
        chown -R app:app /app
        exec su app -c "exec $0"
    fi
else
    echo "Running as non-root user: $(id)"
fi

# At this point we're running as the app user
echo "✓ Application setup complete"

# Start the application
echo "Starting application server..."

if [ "$FLASK_ENV" = "development" ]; then
    echo "Running in development mode with Flask dev server"
    exec python3 app.py
else
    echo "Running in production mode with Gunicorn"
    exec gunicorn --config gunicorn.conf.py app:app
fi