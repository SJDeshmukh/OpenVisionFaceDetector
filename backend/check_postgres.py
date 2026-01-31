import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

def check_postgres():
    # Try connecting to default 'postgres' database
    # Common users: 'postgres', 'hashteelab', or current user
    users = ['postgres', 'hashteelab', os.environ.get('USER')]
    
    conn = None
    connected_user = None
    
    for user in users:
        if not user: continue
        try:
            print(f"Trying to connect as user '{user}'...")
            conn = psycopg2.connect(dbname='postgres', user=user, host='localhost')
            connected_user = user
            print(f"Success! Connected as '{user}'.")
            break
        except Exception as e:
            print(f"Failed as '{user}': {e}")
            
    if not conn:
        print("Could not connect to PostgreSQL with common users.")
        return

    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    cursor = conn.cursor()
    
    # Check if 'face_db' exists
    db_name = 'face_db'
    cursor.execute(f"SELECT 1 FROM pg_database WHERE datname = '{db_name}'")
    exists = cursor.fetchone()
    
    if not exists:
        print(f"Database '{db_name}' does not exist. Creating...")
        try:
            cursor.execute(f"CREATE DATABASE {db_name}")
            print(f"Database '{db_name}' created successfully.")
        except Exception as e:
            print(f"Failed to create database: {e}")
    else:
        print(f"Database '{db_name}' already exists.")
        
    cursor.close()
    conn.close()
    
    # Print the connection string to use
    print(f"\nRecommended DATABASE_URL=postgresql://{connected_user}@localhost/{db_name}")

import os
if __name__ == "__main__":
    check_postgres()
