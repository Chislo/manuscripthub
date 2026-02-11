import json
import google.generativeai as genai
import os
import time

secrets_path = '.streamlit/secrets.toml'
gemini_key = None
if os.path.exists(secrets_path):
    with open(secrets_path, 'r') as f:
        for line in f:
            if 'GEMINI_API_KEY' in line:
                gemini_key = line.split('=')[1].strip().strip('"')

if not gemini_key:
    print("API Key not found.")
    exit(1)

genai.configure(api_key=gemini_key)
model = genai.GenerativeModel("gemini-flash-latest")

file_path = 'journal_metadata.json'

BATCH_SIZE = 50
NUM_BATCHES = 10 # 500 journals

def run_automated_fix():
    print(f"Loading {file_path}...")
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    total_updated = 0
    
    for i in range(NUM_BATCHES):
        scimago = [k for k, v in data.items() if 'scimagojr.com' in v.get('homepage_url', '')]
        scimago.sort(key=lambda x: data[x].get('sjr', 0), reverse=True)
        journals_to_fix = scimago[:BATCH_SIZE]

        if not journals_to_fix:
            print("No more journals with Scimago links found.")
            break

        print(f"--- Batch {i+1}/{NUM_BATCHES}: Resolving {len(journals_to_fix)} journals ---")
        
        prompt = f"""For each academic journal in the list below, provide its official homepage URL. 
        Return the result as a JSON object where the key is the journal name and the value is the URL string.

        Journals:
        {', '.join(journals_to_fix)}
        """

        try:
            response = model.generate_content(prompt)
            raw_text = response.text.strip()
            if "```json" in raw_text:
                raw_text = raw_text.split("```json")[1].split("```")[0].strip()
            elif "```" in raw_text:
                raw_text = raw_text.split("```")[1].split("```")[0].strip()
            
            url_map = json.loads(raw_text)
            batch_count = 0
            for journal, url in url_map.items():
                if journal in data:
                    data[journal]['homepage_url'] = url
                    batch_count += 1
            
            total_updated += batch_count
            print(f"Batch {i+1} complete. Updated {batch_count} URLs. Total so far: {total_updated}")

        except Exception as e:
            print(f"Error in batch {i+1}: {e}")
            break
        
        # Rate limit safety
        if i < NUM_BATCHES - 1:
            time.sleep(4)

    print(f"\nSaving updated data to {file_path}...")
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4)
    
    print(f"DONE. Total updated in this session: {total_updated}")

if __name__ == "__main__":
    run_automated_fix()
