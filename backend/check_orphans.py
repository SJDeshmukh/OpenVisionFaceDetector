"""Diagnostic: Find orphaned attendance/parent data that references deleted faces."""
import psycopg2
from psycopg2.extras import DictCursor

def check_orphans():
    db_url = "postgresql://postgres:postgres@localhost:5432/face_db"
    conn = psycopg2.connect(db_url)
    c = conn.cursor(cursor_factory=DictCursor)

    print("=== Orphaned Data Diagnostic ===\n")

    # 1. Attendance records whose person_id no longer exists in faces
    c.execute("""
        SELECT COUNT(*) FROM attendance a
        WHERE a.person_id IS NOT NULL
        AND NOT EXISTS (SELECT 1 FROM faces f WHERE f.id = a.person_id)
    """)
    orphan_att = c.fetchone()[0]
    print(f"Orphaned attendance records (person_id not in faces): {orphan_att}")

    # 2. student_parents linking to deleted faces
    c.execute("""
        SELECT COUNT(*) FROM student_parents sp
        WHERE NOT EXISTS (SELECT 1 FROM faces f WHERE f.id = sp.person_id)
    """)
    orphan_sp = c.fetchone()[0]
    print(f"Orphaned student_parents records: {orphan_sp}")

    # 3. parent_users with selected_person_id pointing to deleted faces
    c.execute("""
        SELECT COUNT(*) FROM parent_users pu
        WHERE pu.selected_person_id IS NOT NULL
        AND NOT EXISTS (SELECT 1 FROM faces f WHERE f.id = pu.selected_person_id)
    """)
    orphan_pu = c.fetchone()[0]
    print(f"Orphaned parent_users (stale selected_person_id): {orphan_pu}")

    # 4. person_embeddings for deleted faces
    c.execute("""
        SELECT COUNT(*) FROM person_embeddings pe
        WHERE NOT EXISTS (SELECT 1 FROM faces f WHERE f.id = pe.person_id)
    """)
    orphan_emb = c.fetchone()[0]
    print(f"Orphaned person_embeddings: {orphan_emb}")

    # 5. system_users for deleted faces
    c.execute("""
        SELECT COUNT(*) FROM system_users su
        WHERE su.person_id IS NOT NULL
        AND NOT EXISTS (SELECT 1 FROM faces f WHERE f.id = su.person_id)
    """)
    orphan_su = c.fetchone()[0]
    print(f"Orphaned system_users: {orphan_su}")

    total = orphan_att + orphan_sp + orphan_pu + orphan_emb + orphan_su
    print(f"\n{'✅ No orphans found!' if total == 0 else f'⚠️  Total orphaned records: {total}'}")

    if total > 0:
        print("\nTo clean up existing orphans, run:")
        print("  python backend/cleanup_orphans.py")

    conn.close()

if __name__ == "__main__":
    check_orphans()
