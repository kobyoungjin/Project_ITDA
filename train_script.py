import urllib.parse
import urllib.request
import json

base_url = 'http://localhost:8000/api/collect/url'
train_url = 'http://localhost:8000/api/collect/train'

targets = [
    {
        'label': '자신,나,저,내',
        'url': 'http://sldict.korean.go.kr/multimedia/multimedia_files/convert/20191029/632250/MOV000255787_700X466.mp4'
    },
    {
        'label': '너,네,자네',
        'url': 'http://sldict.korean.go.kr/multimedia/multimedia_files/convert/20191014/627265/MOV000251996_700X466.mp4'
    }
]

for t in targets:
    req_url = f"{base_url}?label={urllib.parse.quote(t['label'])}&url={urllib.parse.quote(t['url'])}"
    print(f"Processing: {t['label']}...")
    req = urllib.request.Request(req_url, method='POST')
    try:
        with urllib.request.urlopen(req) as response:
            res = json.loads(response.read().decode())
            print('Result:', res)
    except Exception as e:
        print('Error:', e)

print('Training KNN model...')
req = urllib.request.Request(train_url, method='POST', headers={'Content-Type': 'application/json'}, data=b'{"n_neighbors": 5}')
try:
    with urllib.request.urlopen(req) as response:
        res = json.loads(response.read().decode())
        print('Train Result:', res.get('message', res))
except Exception as e:
    print('Train Error:', e)
