import redis
import time
import os
import subprocess

# Configuration
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
QUEUE_NAME = os.environ.get("CELERY_QUEUE", "normal_priority")
THRESHOLD = int(os.environ.get("AUTOSCALE_THRESHOLD", "5"))  # Scale up if more than 5 tasks are pending
MAX_WORKERS = int(os.environ.get("MAX_WORKERS", "31"))
MIN_WORKERS = int(os.environ.get("MIN_WORKERS", "1"))
CHECK_INTERVAL = int(os.environ.get("AUTOSCALE_INTERVAL", "5"))

def get_queue_length():
    try:
        r = redis.from_url(REDIS_URL)
        # Celery stores the queue as a list in Redis
        return r.llen(QUEUE_NAME)
    except Exception as e:
        print(f"Error checking redis: {e}")
        return 0

def scale_workers(count):
    print(f"[AUTOSCALE] Scaling to {count} workers...")
    try:
        subprocess.run(["docker-compose", "up", "-d", "--scale", f"worker={count}"], check=True)
    except Exception as e:
        print(f"Error scaling: {e}")

def monitor_and_scale():
    current_workers = MIN_WORKERS
    print(f"Starting auto-scale monitor on {QUEUE_NAME}...")
    
    while True:
        qlen = get_queue_length()
        print(f"Current Queue Length: {qlen}")
        
        # Simple Logic: Scale up if queue > threshold
        if qlen > THRESHOLD:
            new_count = min(MAX_WORKERS, current_workers + 1)
            if new_count != current_workers:
                scale_workers(new_count)
                current_workers = new_count
        
        # Scale down if queue is empty
        elif qlen == 0 and current_workers > MIN_WORKERS:
            scale_workers(MIN_WORKERS)
            current_workers = MIN_WORKERS
            
        time.sleep(5)  # Check every 5 seconds

if __name__ == "__main__":
    monitor_and_scale()
