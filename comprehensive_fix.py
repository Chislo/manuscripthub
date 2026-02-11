import json

file_path = 'journal_metadata.json'
with open(file_path, 'r', encoding='utf-8') as f:
    data = json.load(f)

# 1. 100% Gold OA Publishers (Paid)
gold_oa_pubs = [
    'MDPI', 'Frontiers Media', 'Hindawi', 'PLOS', 'PeerJ', 
    'BioMed Central', 'BMC', 'Cogent', 'Dove Medical', 'Dovepress',
    'Open Library of Humanities' # Actually this one IS Diamond OA, so I should EXCLUDE it.
]

# 2. Major Commercial Publishers (Mostly Hybrid/Paid OA)
major_pubs = [
    'Elsevier', 'Springer', 'Wiley', 'Taylor and Francis', 'Taylor & Francis', 
    'Sage', 'Nature', 'Oxford University Press', 'OUP', 
    'Cambridge University Press', 'CUP', 'Emerald', 'World Scientific',
    'Brill', 'De Gruyter', 'Bentham Science', 'Wiley-Blackwell'
]

stats = {
    'gold_fixed': 0,
    'major_fixed': 0
}

for k, v in data.items():
    pub = v.get('publisher', '')
    
    # Heuristic 1: Gold OA Publishers usually charge APC
    if any(g.lower() in pub.lower() for g in gold_oa_pubs):
        # EXCEPTION: Open Library of Humanities is genuine Diamond OA
        if "Open Library of Humanities" in pub:
            continue
        if v.get('free_to_author') == True and v.get('apc') == False:
            v['apc'] = True
            v['open_access'] = True
            v['free_to_author'] = False
            stats['gold_fixed'] += 1
            
    # Heuristic 2: Major Publishers rarely do Diamond OA for high SJR
    elif any(m.lower() in pub.lower() for m in major_pubs):
        if v.get('open_access') == True and v.get('apc') == False and v.get('free_to_author') == True:
            # We assume it's actually Hybrid or Gold OA (Paid)
            v['apc'] = True
            v['open_access'] = True
            v['free_to_author'] = False
            stats['major_fixed'] += 1

with open(file_path, 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=4)

print(f"Fixed {stats['gold_fixed']} Gold OA entries and {stats['major_fixed']} Major Publisher entries.")
