"""Move planned MPC files into a same-drive quarantine folder, or undo a previous move.

  py -I mpc_quarantine.py apply <plan.csv> <source_root> <quarantine_root> <manifest.csv>
  py -I mpc_quarantine.py undo  <manifest.csv> [X:]

undo finds the quarantine on its recorded drive, else on whichever MPC drive (by volume name) holds it,
else on the drive you name - so it works if the MPC mounts on a different letter than when the move ran.

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

def _on(drive, p):
    return drive + os.path.splitdrive(p)[1]

def remap(rows, drive=None):
    """Manifest paths carry the drive letter the MPC had that day. Re-point them if it came back on another one:
    an explicit drive, else whichever MPC drive (found by volume name) holds the quarantined files."""
    if not rows:
        return rows
    old = os.path.splitdrive(rows[0]['destination'])[0]
    probe = rows[:50]
    if drive is None:
        if any(os.path.exists(r['destination']) for r in probe):
            return rows
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import paths
        drive = next((d[:2] for d in paths.mpc_drives().values()
                      if any(os.path.exists(_on(d[:2], r['destination'])) for r in probe)), None)
        if drive is None:
            sys.exit(f'quarantined files not found on {old} or on any MPC drive - connect the MPC (Controller Mode) '
                     'or name the drive: undo <manifest.csv> X:')
    drive = os.path.splitdrive(drive)[0] or drive.rstrip('\\/')
    if drive.lower() == old.lower():
        return rows
    print(f'manifest drive {old} -> {drive}')
    return [{**r, 'source': _on(drive, r['source']), 'destination': _on(drive, r['destination'])} for r in rows]

def undo(manifest, drive=None):
    rows = remap([r for r in csv.DictReader(open(manifest, encoding='utf-8')) if r['operation'] == 'move'], drive)
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
        undo(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    else:
        sys.exit(__doc__)
