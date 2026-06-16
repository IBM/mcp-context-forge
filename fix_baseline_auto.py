import json
import os

with open('.secrets.baseline', 'r', encoding='utf-8') as f:
    data = json.load(f)

files = list(data.get('results', {}).keys())
removed_count = 0

for filepath in files:
    if not os.path.exists(filepath):
        # File was deleted, remove it from baseline
        del data['results'][filepath]
        print(f"Removed deleted file from baseline: {filepath}")
        continue
    
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        
    entries = data['results'][filepath]
    valid_entries = []
    
    for entry in entries:
        line_num = entry['line_number']
        # line numbers are 1-indexed
        if line_num <= len(lines):
            line_content = lines[line_num - 1]
            if '# pragma: allowlist secret' in line_content:
                print(f"Removing secret from {filepath}:{line_num} due to pragma")
                removed_count += 1
                continue
        valid_entries.append(entry)
        
    if valid_entries:
        data['results'][filepath] = valid_entries
    else:
        del data['results'][filepath]
        print(f"Removed entire file from baseline: {filepath} (no secrets left)")

print(f"Total entries removed: {removed_count}")

with open('.secrets.baseline', 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2)

# Ensure newline at EOF and correct formatting if needed
with open('.secrets.baseline', 'r', encoding='utf-8') as f:
    content = f.read()

with open('.secrets.baseline', 'w', encoding='utf-8', newline='\n') as f:
    f.write(content + '\n')
