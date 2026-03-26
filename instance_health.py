import requests
import time

INVIDIOUS_INSTANCES = [
    'https://invidious.io.lol',
    'https://yewtu.be',
    'https://invidious.privacydev.net',
    'https://inv.riverside.rocks',
    'https://invidious.flokinet.to',
    'https://invidious.snopyta.org',
    'https://inv.vern.cc',
    'https://invidious.kavin.rocks',
    'https://vid.puffyan.us',
]

def test_instances():
    working = []
    for instance in INVIDIOUS_INSTANCES:
        try:
            start = time.time()
            response = requests.get(f"{instance}/api/v1/stats", timeout=10)
            latency = (time.time() - start) * 1000
            
            if response.status_code == 200:
                working.append({
                    'url': instance,
                    'latency': f"{latency:.0f}ms",
                    'status': 'OK'
                })
                print(f"✅ {instance} - {latency:.0f}ms")
            else:
                print(f"❌ {instance} - Status: {response.status_code}")
        except Exception as e:
            print(f"❌ {instance} - Error: {str(e)[:50]}")
    
    print(f"\nWorking instances: {len(working)}/{len(INVIDIOUS_INSTANCES)}")
    return working

if __name__ == '__main__':
    test_instances()