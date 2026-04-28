import glob, os, re, collections

files = [os.path.basename(f) for f in glob.glob(r'c:\Users\ComHolic\Documents\GitHub\Project_ITDA\frontend\data\ksl_motions\*.json')]
base_counts = collections.defaultdict(list)

for f in files:
    if not f.startswith('WORD') and not f.startswith('index') and not f.startswith('_mapping'):
        base = re.sub(r'_[0-9]+\.json$', '', f).replace('.json', '')
        base_counts[base].append(f)

multi = {k: v for k, v in base_counts.items() if len(v) > 1}

with open(r'c:\Users\ComHolic\Documents\GitHub\Project_ITDA\multi_words.txt', 'w', encoding='utf-8') as out:
    out.write(f"Total words with variations: {len(multi)}\n\n")
    for k, v in sorted(multi.items(), key=lambda x: len(x[1]), reverse=True):
        out.write(f"{k} ({len(v)} variants): {', '.join(sorted(v))}\n")
