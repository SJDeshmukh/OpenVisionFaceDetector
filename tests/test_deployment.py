import unittest
import os
import sys
import importlib
from unittest.mock import patch, MagicMock
import shutil

# Add backend to path
sys.path.append(os.path.join(os.path.dirname(__file__), '../backend'))

class TestDeploymentConfig(unittest.TestCase):
    def setUp(self):
        # Clear env vars before each test to ensure isolation
        self.original_env = os.environ.copy()
        
        # Rename .env to prevent loading it
        self.env_path = os.path.join(os.path.dirname(__file__), '../backend/.env')
        self.bak_path = self.env_path + '.bak'
        if os.path.exists(self.env_path):
            os.rename(self.env_path, self.bak_path)

        # Remove config from sys.modules to ensure fresh import
        if 'config' in sys.modules:
            del sys.modules['config']
        if 'backend.config' in sys.modules:
            del sys.modules['backend.config']

    def tearDown(self):
        # Restore .env
        if os.path.exists(self.bak_path):
            os.rename(self.bak_path, self.env_path)
            
        os.environ.clear()
        os.environ.update(self.original_env)
        
        # Remove config from sys.modules
        if 'config' in sys.modules:
            del sys.modules['config']
        if 'backend.config' in sys.modules:
            del sys.modules['backend.config']

    def test_config_load_local_defaults(self):
        """Test config falls back to local defaults when no env vars set"""
        # Ensure no conflicting env vars
        os.environ.pop('RENDER_EXTERNAL_URL', None)
        os.environ.pop('BACKEND_URL', None)
        os.environ.pop('DOMAIN_NAME', None)
        os.environ.pop('PORT', None)
        os.environ.pop('PROTOCOL', None)
        
        import config
        self.assertEqual(config.DOMAIN_NAME, "localhost")
        self.assertEqual(config.PORT, 5001)
        self.assertEqual(config.PROTOCOL, "http")
        self.assertEqual(config.BASE_URL, "http://localhost:5001")

    def test_config_load_generic_env(self):
        """Test config respects generic environment variables (EC2/VPS case)"""
        os.environ['DOMAIN_NAME'] = 'test.com'
        os.environ['PORT'] = '8000'
        os.environ['PROTOCOL'] = 'https'
        os.environ['BACKEND_URL'] = 'https://api.test.com'
        
        import config
        self.assertEqual(config.DOMAIN_NAME, 'test.com')
        self.assertEqual(config.PORT, 8000)
        self.assertEqual(config.PROTOCOL, 'https')
        self.assertEqual(config.BASE_URL, 'https://api.test.com')

    def test_config_load_render_env(self):
        """Test config respects Render environment variables"""
        os.environ['RENDER_EXTERNAL_URL'] = 'https://render-app.com'
        # Clear other vars to ensure fallback works
        os.environ.pop('BACKEND_URL', None)
        
        import config
        self.assertEqual(config.RENDER_URL, 'https://render-app.com')
        # Should fallback to render url if backend url not set
        self.assertEqual(config.BASE_URL, 'https://render-app.com')

    @patch('app.check_vendor_status')
    @patch('app.verify_token')
    def test_authenticate_vendor_access(self, mock_verify, mock_check_vendor):
        """Test multi-tenancy authentication logic"""
        # We need to mock sqlite3.connect BEFORE importing app if it connects at module level
        # But app.py connects inside the function.
        
        from app import authenticate_vendor_access, app
        
        # Mock Request Context
        with app.test_request_context(headers={'Authorization': 'Bearer valid_token'}):
            # Case 1: Valid SuperAdmin
            mock_verify.return_value = {'username': 'superadmin', 'role': 'super_admin'}
            mock_check_vendor.return_value = (True, "SuperAdmin")
            
            with patch('sqlite3.connect') as mock_conn:
                mock_cursor = MagicMock()
                mock_conn.return_value.cursor.return_value = mock_cursor
                
                # Mock fetchone to return a dict-like object (for user['vendor_id'])
                # Superadmin typically has vendor_id=None or we simulate it
                mock_user = {'vendor_id': None, 'role': 'super_admin'}
                mock_cursor.fetchone.return_value = mock_user
                
                vendor_id, error = authenticate_vendor_access()
                
                if error:
                    print(f"\nAuth Error: {error[0].get_json() if hasattr(error[0], 'get_json') else error}")
                
                # Should return None (superadmin) and no error
                self.assertIsNone(error)
                self.assertIsNone(vendor_id)

    def test_dockerfile_paths(self):
        """Verify key files referenced in Dockerfile exist"""
        root_dir = os.path.join(os.path.dirname(__file__), '..')
        
        required_files = [
            'web-dashboard/package.json',
            'backend/requirements.txt',
            'backend/app.py',
            'nginx.conf',
            'entrypoint.sh'
        ]
        
        for f in required_files:
            path = os.path.join(root_dir, f)
            self.assertTrue(os.path.exists(path), f"File missing: {f}")

if __name__ == '__main__':
    unittest.main()
