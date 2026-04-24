import psycopg2
from psycopg2.extras import DictCursor

def check_pg_schema():
    db_url = "postgresql://postgres:postgres@localhost:5432/face_db"
    
    try:
        conn = psycopg2.connect(db_url)
        c = conn.cursor(cursor_factory=DictCursor)
        
        # Check table definition/constraints
        c.execute("""
            SELECT 
                conname as constraint_name, 
                pg_get_constraintdef(c.oid) as constraint_definition
            FROM pg_constraint c
            JOIN pg_namespace n ON n.oid = c.connamespace
            WHERE conrelid = 'person_embeddings'::regclass;
        """)
        constraints = c.fetchall()
        print("Constraints on person_embeddings:")
        for con in constraints:
            print(f" - {con['constraint_name']}: {con['constraint_definition']}")
            
        conn.close()
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_pg_schema()
