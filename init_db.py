#!/usr/bin/env python3
"""
Database initialization script for CalDAV Web Client
This script can be run separately to initialize the database
"""

import os
import sys
import sqlite3
from pathlib import Path

def test_directory_permissions():
    """Test if we can write to the data directory"""
    data_dir = Path('/app/data')
    
    print(f"Data directory: {data_dir.absolute()}")
    print(f"Data directory exists: {data_dir.exists()}")
    
    if not data_dir.exists():
        try:
            data_dir.mkdir(parents=True, exist_ok=True)
            print("✓ Created data directory")
        except Exception as e:
            print(f"✗ Cannot create data directory: {e}")
            return False
    
    # Test write permissions
    try:
        test_file = data_dir / "test_write.tmp"
        test_file.write_text("test")
        test_file.unlink()
        print("✓ Data directory is writable")
        return True
    except Exception as e:
        print(f"✗ Cannot write to data directory: {e}")
        return False

def test_sqlite_direct():
    """Test SQLite database creation directly"""
    db_path = '/app/data/caldav_client.db'
    
    try:
        # Test basic SQLite operations
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Create a test table
        cursor.execute('CREATE TABLE IF NOT EXISTS test_table (id INTEGER PRIMARY KEY)')
        cursor.execute('INSERT INTO test_table (id) VALUES (1)')
        cursor.execute('SELECT * FROM test_table')
        result = cursor.fetchone()
        
        # Clean up
        cursor.execute('DROP TABLE test_table')
        conn.commit()
        conn.close()
        
        print(f"✓ SQLite test successful: {db_path}")
        print(f"  Test result: {result}")
        return True
        
    except Exception as e:
        print(f"✗ SQLite test failed: {e}")
        return False

def initialize_flask_database():
    """Initialize the Flask application database"""
    try:
        # Add current directory to Python path
        sys.path.insert(0, '/app')
        
        # Import Flask app and database
        from app import app, db
        
        with app.app_context():
            # Create all tables
            db.create_all()
            
            # Test that tables were created
            tables = db.engine.table_names()
            print(f"✓ Flask database initialized")
            print(f"  Created tables: {tables}")
            
            return True
            
    except Exception as e:
        print(f"✗ Flask database initialization failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Main initialization function"""
    print("=" * 50)
    print("CalDAV Web Client - Database Initialization")
    print("=" * 50)
    
    # Step 1: Test directory permissions
    print("\n1. Testing directory permissions...")
    if not test_directory_permissions():
        print("FAILED: Directory permission test")
        sys.exit(1)
    
    # Step 2: Test SQLite directly
    print("\n2. Testing SQLite database...")
    if not test_sqlite_direct():
        print("FAILED: SQLite test")
        sys.exit(1)
    
    # Step 3: Initialize Flask database
    print("\n3. Initializing Flask database...")
    if not initialize_flask_database():
        print("FAILED: Flask database initialization")
        sys.exit(1)
    
    print("\n" + "=" * 50)
    print("✓ Database initialization completed successfully!")
    print("=" * 50)

if __name__ == "__main__":
    main()
