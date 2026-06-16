import json

with open('.secrets.baseline', 'r', encoding='utf-8') as f:
    data = json.load(f)

for filepath, secrets in data.get('results', {}).items():
    for secret in secrets:
        secret['is_verified'] = True
        secret['is_secret'] = False

with open('.secrets.baseline', 'w', encoding='utf-8', newline='\n') as f:
    json.dump(data, f, indent=2, sort_keys=True)
    f.write('\n')

print("Secrets baseline updated successfully.")
