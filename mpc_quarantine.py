"""Move planned MPC files into a same-drive quarantine folder, or undo a previous move.

  py -I mpc_quarantine.py apply <plan.csv> <source_root> <quarantine_root> <manifest.csv>
  py -I mpc_quarantine.py undo  <manifest.csv>

plan.csv needs a 'relpath' column (relative to source_root). Moves are os.rename only
(same volume), never overwrite, and every move is logged to the manifest before the next one.
"""
import csv, hashlib, os, sys, datetime

def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()

def apply(plan, src_root, q_root, manifest):
    if os.path.splitdrive(src_root)[0].lower() != os.path.splitdrive(q_root)[0].lower():
        sys.exit('refusing: quarantine must be on the same drive as the source')
    rows = list(csv.DictReader(open(plan, encoding='utf-8')))
    for r in rows:  # preflight everything before touching anything
        s = os.path.join(src_root, r['relpath']); d = os.path.join(q_root, r['relpath'])
        if not os.path.isfile(s):
            sys.exit(f'refusing: missing source {s}')
        if os.path.exists(d):
            sys.exit(f'refusing: destination exists {d}')
    new = not os.path.exists(manifest)
    with open(manifest, 'a', newline='', encoding='utf-8') as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(['utc', 'operation', 'source', 'destination', 'bytes', 'sha256'])
        for r in rows:
            s = os.path.join(src_root, r['relpath']); d = os.path.join(q_root, r['relpath'])
            size, digest = os.path.getsize(s), sha(s)
            os.makedirs(os.path.dirname(d), exist_ok=True)
            os.rename(s, d)
            if os.path.getsize(d) != size:
                sys.exit(f'size mismatch after move: {d}')
            w.writerow([datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'), 'move', s, d, size, digest])
            fh.flush()
    print(f'moved {len(rows)} files -> {q_root}')

def undo(manifest):
    rows = [r for r in csv.DictReader(open(manifest, encoding='utf-8')) if r['operation'] == 'move']
    for r in reversed(rows):
        if os.path.exists(r['source']):
            sys.exit(f'refusing: original path occupied {r["source"]}')
        os.makedirs(os.path.dirname(r['source']), exist_ok=True)
        os.rename(r['destination'], r['source'])
    print(f'restored {len(rows)} files')

if __name__ == '__main__':
    if sys.argv[1] == 'apply':
        apply(*sys.argv[2:6])
    elif sys.argv[1] == 'undo':
        undo(sys.argv[2])
    else:
        sys.exit(__doc__)
