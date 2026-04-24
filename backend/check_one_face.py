import psycopg2
from psycopg2.extras import DictCursor
import json
import base64

def check_one_face():
    db_url = "postgresql://postgres:postgres@localhost:5432/face_db"
    
    try:
        conn = psycopg2.connect(db_url)
        c = conn.cursor(cursor_factory=DictCursor)
        
        # Get the most recent face
        c.execute("SELECT id, name, templates FROM faces ORDER BY id DESC LIMIT 1")
        row = c.fetchone()
        if not row:
            print("No faces found.")
            return
            
        print(f"Checking Face ID: {row['id']} ({row['name']})")
        templates = row['templates']
        
        try:
            t_list = json.loads(templates)
            print(f"Templates is a JSON list with {len(t_list)} items.")
        except Exception:
            print("Templates is not a JSON list (or empty).")
            # Maybe it's a single base64 string
            if templates and len(templates) > 100:
                print("Templates appears to be a single large string/blob.")
            else:
                print(f"Templates content: {templates[:50]}...")
                
        # Check person_embeddings for this ID
        c.execute("SELECT COUNT(*) FROM person_embeddings WHERE person_id = %s", (row['id'],))
        emb_count = c.fetchone()[0]
        print(f"Embeddings in person_embeddings for this ID: {emb_count}")
        
        conn.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_one_face()
