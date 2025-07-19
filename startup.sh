#!/bin/bash
# Portable startup script for CalDAV Web Client
# Automatically adapts to any host system UID/GID

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
        
        # Ensure data directory is writable
        chown -R app:app /app/data
        chmod 755 /app/data
        
        # Switch to app user and re-exec this script
        echo "Switching to app user..."
        exec su app -c "DATABASE_URL=sqlite:////app/data/caldav_client.db exec $0"
    else
        echo "No data directory mounted, creating app user with default UID"
        useradd -u 1000 -d /home/app -m -s /bin/bash app 2>/dev/null || true
        chown -R app:app /app
        exec su app -c "DATABASE_URL=sqlite:////tmp/caldav_client.db exec $0"
    fi
else
    echo "Running as non-root user: $(id)"
fi

# At this point we're running as the app user
# Determine the best database location
if [ -w "/app/data" ] 2>/dev/null; then
    echo "✓ Using /app/data for database storage"
    export DATABASE_URL="sqlite:////app/data/caldav_client.db"
    DB_DIR="/app/data"
elif [ -d "/app/data" ]; then
    echo "⚠ /app/data exists but not writable, using /tmp"
    export DATABASE_URL="sqlite:////tmp/caldav_client.db"
    DB_DIR="/tmp"
else
    echo "⚠ No /app/data directory, using /tmp"
    export DATABASE_URL="sqlite:////tmp/caldav_client.db"
    DB_DIR="/tmp"
    mkdir -p /tmp
fi

echo "Database URL: $DATABASE_URL"
echo "Database directory: $DB_DIR"

# Test database directory
if ! touch "$DB_DIR/.test" 2>/dev/null; then
    echo "✗ Cannot write to database directory: $DB_DIR"
    exit 1
else
    rm -f "$DB_DIR/.test"
    echo "✓ Database directory is writable"
fi

# Initialize database
echo "Initializing database..."
python3 -c "
import os
import sys
sys.path.insert(0, '/app')

# Ensure DATABASE_URL is set in Python environment
os.environ['DATABASE_URL'] = '$DATABASE_URL'

try:
    from app import app, db
    with app.app_context():
        # Print actual database URI being used
        print(f'Database URI: {app.config[\"SQLALCHEMY_DATABASE_URI\"]}')
        
        db.create_all()
        print('✓ Database tables created successfully')
        
        # Test database connection
        result = db.session.execute(db.text('SELECT 1')).scalar()
        print(f'✓ Database connection test: {result}')
        
        # List created tables
        tables = db.inspect(db.engine).get_table_names()
        print(f'✓ Created tables: {tables}')
        
except Exception as e:
    print(f'✗ Database initialization failed: {e}')
    import traceback
    traceback.print_exc()
    sys.exit(1)
"

if [ $? -ne 0 ]; then
    echo "Database initialization failed, exiting..."
    exit 1
fi

echo "✓ Database setup complete"

# Start the application
echo "Starting application server..."

if [ "$FLASK_ENV" = "development" ]; then
    echo "Running in development mode with Flask dev server"
    exec python3 app.py
else
    echo "Running in production mode with Gunicorn"
    exec gunicorn --config gunicorn.conf.py app:app
fi
