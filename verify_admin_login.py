import os

from app import app

client = app.test_client()
username = os.getenv('ADMIN_USERNAME', '')
password = os.getenv('ADMIN_PASSWORD', '')
print('username=', username)
print('password=', password)
response = client.post('/admin/login', data={'username': username, 'password': password})
print('status', response.status_code)
print('location', response.location)
print('body', response.get_data(as_text=True)[:200])
