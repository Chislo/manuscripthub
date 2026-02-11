import json

file_path = 'journal_metadata.json'
with open(file_path, 'r', encoding='utf-8') as f:
    data = json.load(f)

majors = ['Elsevier', 'Springer', 'Wiley', 'Taylor', 'Francis', 'Sage', 'Frontiers', 'Hindawi', 'Nature', 'Oxford', 'Cambridge', 'Emerald', 'MDPI']
results = []

for k, v in data.items():
    if v.get('open_access') == True and v.get('apc') == False and v.get('free_to_author') == True:
        pub = v.get('publisher', '')
        if any(m.lower() in pub.lower() for m in majors):
            results.append({
                'journal': k,
                'publisher': pub,
                'sjr': v.get('sjr')
            })

results.sort(key=lambda x: x.get('sjr', 0), reverse=True)

print(json.dumps(results[:50], indent=4))
