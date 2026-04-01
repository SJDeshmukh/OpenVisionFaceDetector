import sys
import os
import threading
import time

# Add backend to sys.path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from db_factory import get_db_connection, get_pg_pool, DATABASE_URL

def test_pool_initialization():
    print("--- Testing Pool Initialization ---")
    if not DATABASE_URL:
        print("PostgreSQL not configured (no DATABASE_URL). Skipping Postgres pool test.")
        return True
    
    pool = get_pg_pool()
    if pool:
        print(f"SUCCESS: Pool initialized. Min: {pool.minconn}, Max: {pool.maxconn}")
        return True
    else:
        print("FAILURE: Pool failed to initialize!")
        return False

def simulate_request(req_id):
    try:
        conn = get_db_connection()
        # Simulate some work
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.close()
        # Connection should be released on conn.close()
        conn.close()
        # print(f"Request {req_id} completed.")
    except Exception as e:
        print(f"Request {req_id} failed: {e}")

def test_concurrent_connections():
    print("\n--- Testing Concurrent Connections ---")
    if not DATABASE_URL:
        return True

    threads = []
    start_time = time.time()
    num_requests = 50
    
    print(f"Launching {num_requests} concurrent requests...")
    for i in range(num_requests):
        t = threading.Thread(target=simulate_request, args=(i,))
        threads.append(t)
        t.start()
    
    for t in threads:
        t.join()
    
    duration = time.time() - start_time
    print(f"Finished {num_requests} requests in {duration:.2f}s")
    
    pool = get_pg_pool()
    if pool:
        print(f"Pool status - Used: {len(pool._used) if hasattr(pool, '_used') else 'unknown'}")
        if len(pool._used) == 0:
            print("SUCCESS: All connections returned to pool.")
            return True
        else:
            print(f"WARNING: {len(pool._used)} connections still marked as used.")
            return False
    return True

if __name__ == "__main__":
    s1 = test_pool_initialization()
    s2 = test_concurrent_connections()
    
    if s1 and s2:
        print("\nALL POOL TESTS PASSED")
        sys.exit(0)
    else:
        print("\nPOOL TESTS FAILED")
        sys.exit(1)
