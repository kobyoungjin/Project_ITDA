import urllib.request
import json
req = urllib.request.Request('http://localhost:8000/api/collect/train', method='POST', headers={'Content-Type': 'application/json'}, data=b'{"n_neighbors": 5}')
try:
    with urllib.request.urlopen(req) as res:
        print(res.read().decode())
except Exception as e:
    print(e)
