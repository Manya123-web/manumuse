import json

# Read your current cookies file
with open('cookie.json', 'r') as f:
    cookies_data = json.load(f)

# Convert to simple key-value format
simple_cookies = {}
for cookie in cookies_data:
    name = cookie.get('name')
    value = cookie.get('value')
    if name and value:
        simple_cookies[name] = value

# Save the converted cookies
with open('cookie_simple.json', 'w') as f:
    json.dump(simple_cookies, f, indent=2)

print(f"✅ Converted {len(simple_cookies)} cookies")
print("Saved to cookie_simple.json")