"""Cleanup orphaned records from past deletions where cascade was broken."""
import psycopg2

def cleanup():
    db_url = "postgresql://postgres:postgres@localhost:5432/face_db"
    conn = psycopg2.connect(db_url)
    c = conn.cursor()

    print("=== Cleaning up orphaned records ===\n")

    # 1. Orphaned attendance
    c.execute("""
        DELETE FROM attendance WHERE person_id IS NOT NULL
        AND NOT EXISTS (SELECT 1 FROM faces WHERE id = attendance.person_id)
    """)
    print(f"Deleted {c.rowcount} orphaned attendance records")

    # 2. Orphaned student_parents
    c.execute("""
        DELETE FROM student_parents
        WHERE NOT EXISTS (SELECT 1 FROM faces WHERE id = student_parents.person_id)
    """)
    print(f"Deleted {c.rowcount} orphaned student_parents records")

    # 3. Orphaned parent_users (stale selected_person_id)
    c.execute("""
        UPDATE parent_users SET selected_person_id = NULL
        WHERE selected_person_id IS NOT NULL
        AND NOT EXISTS (SELECT 1 FROM faces WHERE id = parent_users.selected_person_id)
    """)
    print(f"Cleared {c.rowcount} stale parent_users.selected_person_id")

    # 4. Orphaned person_embeddings
    c.execute("""
        DELETE FROM person_embeddings
        WHERE NOT EXISTS (SELECT 1 FROM faces WHERE id = person_embeddings.person_id)
    """)
    print(f"Deleted {c.rowcount} orphaned person_embeddings")

    # 5. Orphaned system_users
    c.execute("""
        DELETE FROM system_users
        WHERE person_id IS NOT NULL
        AND NOT EXISTS (SELECT 1 FROM faces WHERE id = system_users.person_id)
    """)
    print(f"Deleted {c.rowcount} orphaned system_users")

    conn.commit()
    conn.close()
    print("\n✅ Cleanup complete!")

if __name__ == "__main__":
    cleanup()
