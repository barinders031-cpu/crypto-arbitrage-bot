import urllib.request, json

d = json.loads(urllib.request.urlopen('http://localhost:5050/api/state').read())
print('Logs count:', len(d['logs']))
print('Top5 count:', len(d['state']['top5_coins']))
print('Last scan:', d['state']['last_scan_time'])
print()
for c in d['state']['top5_coins']:
    nf = c.get('next_funding', 'N/A').encode('ascii', 'ignore').decode()
    print(f"  {c['coin']:8s} | {c['diff']:7s} | mins_left={c.get('mins_left','?'):3} | {nf} | {c['action']}")
