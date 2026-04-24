import psycopg2
from psycopg2.extras import DictCursor
import os

def check_pg_embeddings():
    db_url = "postgresql://postgres:postgres@localhost:5432/face_db"
    
    print(f"Connecting to PostgreSQL: {db_url}")
    try:
        conn = psycopg2.connect(db_url)
        c = conn.cursor(cursor_factory=DictCursor)
        
        c.execute("SELECT COUNT(*) FROM faces")
        face_count = c.fetchone()[0]
        print(f"Total faces in 'faces' table: {face_count}")
        
        c.execute("SELECT COUNT(*) FROM person_embeddings")
        emb_count = c.fetchone()[0]
        print(f"Total embeddings in 'person_embeddings' table: {emb_count}")
        
        print("\nRecent persons and their embedding counts:")
        c.execute("SELECT person_id, COUNT(*) FROM person_embeddings GROUP BY person_id ORDER BY person_id DESC LIMIT 10")
        for row in c.fetchall():
            print(f"Person ID: {row['person_id']}, Count: {row['count']}")
            
        conn.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_pg_embeddings()
