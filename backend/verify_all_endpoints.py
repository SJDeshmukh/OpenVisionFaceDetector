import sys
import os
import re

# Ensure the backend directory is in the sys.path
_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from app import app

def get_dummy_value(converter_type):
    # Flask converters: string, int, float, path, uuid, etc.
    if converter_type == 'int':
        return '1'
    elif converter_type == 'float':
        return '1.0'
    elif converter_type == 'path':
        return 'dummy/path'
    elif converter_type == 'uuid':
        return '123e4567-e89b-12d3-a456-426614174000'
    else:
        return 'test'

def test_all_endpoints():
    print("Testing all registered endpoints for graceful responses...")
    
    client = app.test_client()
    results = []
    
    for rule in app.url_map.iter_rules():
        if "static" in rule.endpoint or "serve_frontend" in rule.endpoint:
            continue
            
        methods = rule.methods.difference({'OPTIONS', 'HEAD'})
        if not methods:
            continue
            
        # We prefer GET if available, otherwise pick whatever mapping it allows
        method = 'GET' if 'GET' in methods else list(methods)[0]
        
        # Build test URL
        url = str(rule)
        matches = re.finditer(r'<([^>]+)>', url)
        for match in matches:
            full_var = match.group(1)
            parts = full_var.split(':')
            if len(parts) == 2:
                converter, var_name = parts
            else:
                converter = 'string'
            
            dummy_val = get_dummy_value(converter)
            url = url.replace(match.group(0), dummy_val)
            
        print(f"Testing {method} {url:<40} (endpoint: {rule.endpoint:<30}) ...", end=" ")
        sys.stdout.flush()
        
        try:
            if method == 'GET':
                response = client.get(url)
            elif method == 'POST':
                response = client.post(url, json={})
            elif method == 'PUT':
                response = client.put(url, json={})
            elif method == 'DELETE':
                response = client.delete(url)
            elif method == 'PATCH':
                response = client.patch(url, json={})
            else:
                print(f"Skipped method {method}")
                continue
                
            status_code = response.status_code
            if status_code == 500:
                print(f"FAILED (500)")
                results.append((method, url, status_code, "FAIL"))
            else:
                print(f"OK ({status_code})")
                results.append((method, url, status_code, "PASS"))
                
        except Exception as e:
            print(f"ERROR: {str(e)}")
            results.append((method, url, 500, f"ERROR: {str(e)}"))

    print("\n" + "="*80)
    print("ENDPOINT TEST SUMMARY")
    print("="*80)
    fail_count = 0
    passed_count = 0
    for method, url, status, result in results:
        status_str = f"[{status}]" if isinstance(status, int) else ""
        if result != "PASS":
            print(f"FAIL  {method:5}  {url:<40}  {status_str}")
            fail_count += 1
        else:
            passed_count += 1
            
    print(f"\nStats: {passed_count} endpoints passed (handled gracefully), {fail_count} failed (returned 500 or error).")
    
    if fail_count > 0:
        sys.exit(1)

if __name__ == "__main__":
    with app.app_context():
        test_all_endpoints()
