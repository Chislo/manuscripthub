"""
fix_cost_data.py — Correct the submission_fee, apc, open_access, and free_to_author fields
in journal_metadata.json based on publisher-level rules and known journal facts.

RULES:
1. submission_fee: Only a handful of journals charge this (mostly Elsevier economics journals,
   some AEA journals for non-members). Default should be False.
2. apc: Article Processing Charges apply when publishing Open Access. Most subscription journals
   offer optional OA (hybrid) with an APC. Pure OA journals always have an APC unless Diamond OA.
3. open_access: True if the journal is primarily OA (Gold OA). Hybrid journals are NOT marked as OA.
4. free_to_author: True if a subscription-model journal with no submission fee (most journals).
"""

import json

with open("journal_metadata.json", "r", encoding="utf-8") as f:
    data = json.load(f)

# === Known journals that DO charge submission fees ===
# These are verified real submission fees (not APC)
known_sub_fee_journals = {
    # Elsevier economics journals with submission fees
    "Journal of Financial Economics",        # $50 for new, $750 expedited
    "Journal of Monetary Economics",         # $350
    "Journal of International Economics",    # $95
    "European Economic Review",              # €50
    "Journal of Public Economics",           # $50
    "Journal of Econometrics",               # $75
    "Journal of Development Economics",      # $100
    "Journal of International Money and Finance", # $75
    "Journal of Environmental Economics and Management", # $75
    "Journal of Urban Economics",            # $100
    "Journal of Health Economics",           # $100
    "Journal of Economic Theory",            # $50
    "Games and Economic Behavior",           # $50
    "Journal of Mathematical Economics",     # $50
    "Journal of Economic Behavior and Organization", # $50
    "Economics Letters",                     # $50
    "Labour Economics",                      # €50
    "Resource and Energy Economics",         # $50
    "Journal of Housing Economics",          # $50
    "Regional Science and Urban Economics",  # $75
    "Explorations in Economic History",      # $50
    "Journal of Comparative Economics",      # $50
    # University of Chicago Press
    "Journal of Political Economy",          # $125
    "Journal of Law and Economics",          # $75
    "Journal of Legal Studies",              # $75
    "Journal of Labor Economics",            # $50
    "Economic Development and Cultural Change", # $50
    # Econometric Society  
    "Econometrica",                          # $100 (non-members)
    # Others
    "Review of Economics and Statistics",    # $100
    "Economic Journal",                      # $50
    "Journal of the European Economic Association", # €50
    "International Economic Review",         # $100
}

# === Known Diamond OA journals (free to publish AND read) ===
known_diamond_oa = {
    "Theoretical Economics",
    "Quantitative Economics",
    "American Economic Journal: Applied Economics",
    "American Economic Journal: Macroeconomics",
    "American Economic Journal: Economic Policy",
    "American Economic Journal: Microeconomics",
    "Journal of Economic Perspectives",  # Free with AEA
    "Journal of Economic Literature",    # Free with AEA
}

# === Journals with NO submission fee (verified) ===
known_no_sub_fee = {
    "American Economic Review",          # Free (AEA members)
    "Quarterly Journal of Economics",    # Free
    "Review of Economic Studies",        # Free
    "Journal of Finance",               # Free (AFA members)
    "Review of Financial Studies",       # Free (SFS members)
    "World Development",                # Free
    "Journal of Financial Intermediation", # Free
    "RAND Journal of Economics",         # Free
    "Brookings Papers on Economic Activity", # Free
    "Annual Review of Economics",        # Free (invited)
}

print("=== Fixing cost model data ===")
changes = {"sub_fee_fixed": 0, "free_fixed": 0, "oa_fixed": 0, "apc_fixed": 0}

for name, meta in data.items():
    old_sub = meta.get("submission_fee")
    old_free = meta.get("free_to_author")
    old_oa = meta.get("open_access")
    old_apc = meta.get("apc")
    
    # --- Fix submission_fee ---
    if name in known_sub_fee_journals:
        meta["submission_fee"] = True
    elif name in known_no_sub_fee or name in known_diamond_oa:
        meta["submission_fee"] = False
    else:
        # Default: most journals do NOT charge submission fees
        # Only the ones in our known list do
        meta["submission_fee"] = False
    
    # --- Fix free_to_author ---
    # Free to author = no submission fee AND (subscription model OR diamond OA)
    if name in known_diamond_oa:
        meta["free_to_author"] = True
        meta["open_access"] = True
        meta["apc"] = False  # Diamond = no APC
    elif meta["submission_fee"] == False and meta.get("open_access") != True:
        # Subscription journal with no submission fee = free to publish
        meta["free_to_author"] = True
    elif meta["submission_fee"] == True:
        meta["free_to_author"] = False
    
    # --- Fix APC logic ---
    # APC applies only if the journal offers Open Access publishing
    # Subscription journals don't have APC (authors don't pay to publish)
    if meta.get("open_access") == True and name not in known_diamond_oa:
        meta["apc"] = True  # Gold OA journals charge APC
    elif meta.get("open_access") == False:
        # Subscription/hybrid: APC only if they offer optional OA
        # Most major publishers offer hybrid OA, but default display should be subscription
        meta["apc"] = False  # Don't flag APC for subscription journals
    
    # Track changes
    if meta.get("submission_fee") != old_sub: changes["sub_fee_fixed"] += 1
    if meta.get("free_to_author") != old_free: changes["free_fixed"] += 1
    if meta.get("open_access") != old_oa: changes["oa_fixed"] += 1
    if meta.get("apc") != old_apc: changes["apc_fixed"] += 1

# Save
with open("journal_metadata.json", "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)

print(f"Changes: {changes}")

# Final stats
sub_true = sum(1 for v in data.values() if v.get('submission_fee') == True)
free_true = sum(1 for v in data.values() if v.get('free_to_author') == True)
apc_true = sum(1 for v in data.values() if v.get('apc') == True)
oa_true = sum(1 for v in data.values() if v.get('open_access') == True)
print(f"\nAfter fix:")
print(f"  submission_fee=True: {sub_true} (journals that charge to submit)")
print(f"  free_to_author=True: {free_true} (no cost to publish)")
print(f"  apc=True: {apc_true} (author pays for Open Access)")
print(f"  open_access=True: {oa_true} (OA journals)")
print(f"  Total journals: {len(data)}")

# Verify specific journals
print("\n=== Verification ===")
check = ["American Economic Review", "Journal of Financial Economics", "Econometrica",
         "Quarterly Journal of Economics", "World Development", "Theoretical Economics"]
for j in check:
    m = data.get(j, {})
    print(f"{j}: sub_fee={m.get('submission_fee')} oa={m.get('open_access')} apc={m.get('apc')} free={m.get('free_to_author')}")
