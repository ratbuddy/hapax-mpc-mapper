"""
mpc_map.py - map ANY MPC 3 project to the Hapax (engine for the Hapax Mapper app; also usable from a terminal).

  py -I mpc_map.py list "<MPC User drive>\\MPC Documents\\Projects\\My Song.xpj"
  py -I mpc_map.py map  "<MPC User drive>\\MPC Documents\\Projects\\My Song.xpj" [--name "My Song HAPAX"]
                        [--channels "Plugin 003=5,Kit-Foo=10"] [--drum-channel 10] [--no-defs]

list : instrument tracks found and the channel each would get. Writes nothing.
map  : writes <name>.xpj (+ a copy of its _[ProjectData] folder) next to the source. Never edits the source,
       never overwrites. Every mapped track gets:
         - Track Settings: INPUT PORT = the Hapax, INPUT CHANNEL = its channel, MIDI MONITOR = Merge
         - CC 7 = track Volume, CC 10 = Pan
         - plugin tracks: 32 parameters (your saved choices in the data folder, else the plugin's own Q-Link page order),
           pots 1-8 on CC 20-27, the other 24 on spare CCs. Pre-learned only where the plugin's saved state
           decodes reliably (gives each knob's real current value, so loading the project changes nothing).
       Your own MIDI Learn entries are kept unless they clash (same channel+CC, or same target).
       Also writes Hapax definitions for the project (Projects\\<name>\\ and SD-Card\\HAPAX\\).
Formats used were each checked against projects saved by an MPC Live III on MPC 3.10.
"""
import argparse, copy, gzip, json, os, shutil, sys, zlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths
import hapax_integration as hi
import mpc_hapax as mh

TYPE_NAMES = {0: 'Drum', 1: 'Keygroup', 3: 'Plugin', 4: 'MIDI', 7: 'Return', 8: 'Submix', 9: 'Output'}
INSTRUMENT_TYPES = (0, 1, 3)
PLUGIN_PARAM_BASE, PLUGIN_INSTRUMENT = 4096, 256       # learned plugin parameter: 4096 + automationIndex
MIXER_INSTRUMENT = 257                                 # channel strip: parameter 7 = volume, 10 = pan
MIXER = [(7, 7, 'volume', 'Volume'), (10, 10, 'pan', 'Pan')]
MONITOR_MERGE = 3
JUNK_CCS = set(range(120, 128))                        # channel-mode messages (All Notes Off etc.)

def load(path):
    b = open(path, 'rb').read(); pos, out = 0, b''
    while pos < len(b) and b[pos:pos + 2] == b'\x1f\x8b':
        d = zlib.decompressobj(31); out += d.decompress(b[pos:]); pos = len(b) - len(d.unused_data)
    i = out.find(b'{')
    return [h for h in out[:i].decode('ascii', 'replace').split('\n') if h], json.loads(out[i:])

def save(path, hdr, j):
    raw = ('\n'.join(hdr) + '\n').encode('ascii') + json.dumps(j, indent=0).encode('utf-8')  # MPC layout
    with open(path, 'wb') as f:
        f.write(gzip.compress(raw, compresslevel=6))

def plugin_name(t):
    return (t.get('program', {}).get('plugin', {}).get('plugin', {}).get('description') or {}).get('name')

def track_params(t):
    return [(i, n) for i, n, _ in hi.qlink_ordered_params(t)]

def track_label(t):
    return plugin_name(t) or mh.short_name(t.get('program', {}).get('name') or t.get('name', 'Track'))

def plan_channels(tracks, overrides=None, drum_channel=10):
    """overrides: {track number (int) or name (str): channel}."""
    overrides = overrides or {}
    inst = [(n, t) for n, t in enumerate(tracks, 1) if t.get('program', {}).get('type') in INSTRUMENT_TYPES]
    chan = {}
    for key, ch in overrides.items():
        for n, t in inst:
            if str(key) == str(n) or str(key).lower() == t['name'].lower():
                chan[n] = int(ch)
    used = set(chan.values())
    first_drum = next((n for n, t in inst if t['program']['type'] == 0 and n not in chan), None)
    if first_drum is not None and drum_channel not in used:
        chan[first_drum] = drum_channel; used.add(drum_channel)
    for n, t in inst:
        if n not in chan:
            free = next((c for c in range(1, 17) if c not in used), None)
            if free is None:
                break
            chan[n] = free; used.add(free)
    return inst, chan

def analyze(path, overrides=None, drum_channel=10, maps=None):
    """Everything the app shows: tracks, channels, and for plugins the parameter list + current selection."""
    hdr, j = load(path)
    maps = hi.load_maps() if maps is None else maps
    inst, chan = plan_channels(j['data']['tracks'], overrides, drum_channel)
    rows = []
    for n, t in inst:
        plug = plugin_name(t)
        info = {'n': n, 'track': t['name'], 'type': TYPE_NAMES.get(t['program']['type']), 'plugin': plug,
                'channel': chan.get(n), 'params': [], 'selection': [], 'trusted': False, 'kind': None}
        if plug:
            kind = hi.PLUGIN_KINDS.get(plug, 'synth')
            ordered = hi.qlink_ordered_params(t)
            vals = hi.plugin_param_values(t)
            info.update(kind=kind, params=ordered,
                        trusted=plug not in hi.STATE_UNTRUSTED and hi.state_is_plausible(vals, [(i, n_) for i, n_, _ in ordered]),
                        selection=hi.plugin_selection(kind, plug, ordered, maps.get(plug)))
        rows.append(info)
    return {'path': path, 'tracks': rows}

def map_project(path, name=None, overrides=None, drum_channel=10, selections=None, write_defs=True, log=print):
    """selections: {plugin name: rows} from the app (else saved/default choices). Returns a summary dict."""
    src = os.path.abspath(path)
    hdr, j = load(src)
    data = j['data']
    name = name or os.path.splitext(os.path.basename(src))[0] + ' HAPAX'
    dst = os.path.join(os.path.dirname(src), name + '.xpj')
    src_pd = os.path.splitext(src)[0] + '_[ProjectData]'
    dst_pd = os.path.join(os.path.dirname(src), name + '_[ProjectData]')
    if os.path.exists(dst):
        raise FileExistsError(f'{dst} already exists - choose another name')
    port = json.load(open(os.path.join(paths.RESOURCES, 'hapax_port.json')))['inputPort']
    tmpl = json.load(open(os.path.join(paths.RESOURCES, 'learn_entry_template.json')))['entry']
    maps = hi.load_maps()
    selections = selections or {}
    inst, chan = plan_channels(data['tracks'], overrides, drum_channel)

    def entry(track_name, ch, cc, parameter, instrument, label, value):
        e = copy.deepcopy(tmpl)
        e['control']['name'] = f'{track_name} ({label})'
        e['control']['targetData'][0].update({'parameter': parameter, 'track': track_name, 'instrumentIndex': instrument})
        e['control']['controlValue'] = float(value)
        e['mapping'].update({'channel': ch, 'data1': cc})
        return e

    new, report, hapax = [], [], []
    for n, t in inst:
        ch = chan.get(n)
        if ch is None:
            report.append((n, t['name'], None, 'not mapped: no free channel')); continue
        r = t.setdefault('midiInputRoute', {})
        r['inputPort'] = dict(port); r['inputChannel'] = ch
        t.setdefault('midiMonitorable', {})['state'] = MONITOR_MERGE
        typ, plug = t['program']['type'], plugin_name(t)
        rows, learned, note = [], False, []
        if typ == 3 and plug:
            kind = hi.PLUGIN_KINDS.get(plug, 'synth')
            ordered = hi.qlink_ordered_params(t)
            rows = hi.assign_ccs([dict(x) for x in selections.get(plug) or hi.plugin_selection(kind, plug, ordered, maps.get(plug))])
            vals = hi.plugin_param_values(t)
            trusted = plug not in hi.STATE_UNTRUSTED and hi.state_is_plausible(vals, [(i, n_) for i, n_, _ in ordered])
            if plug not in hi.PLUGIN_KINDS and sum(1 for x in rows if x.get('pot')) < hi.MIN_POT_MATCHES and plug not in selections:
                note.append('unknown plugin, few matches - names only, nothing learned'); trusted = False
            if trusted:
                for x in rows:
                    new.append(entry(t['name'], ch, x['cc'], PLUGIN_PARAM_BASE + x['index'], PLUGIN_INSTRUMENT, x['name'], vals[x['index']]))
                learned = True
                note.append(f'{len(rows)} parameters learned')
            else:
                note.append(f'{len(rows)} parameters named on the Hapax, NOT pre-learned (learn by hand)')
        mix = t.get('program', {}).get('mixable', {})
        for cc, param, key, lbl in MIXER:
            new.append(entry(t['name'], ch, cc, param, MIXER_INSTRUMENT, lbl, mix.get(key, 0.5)))
        note.append('vol/pan')
        report.append((n, t['name'], ch, ', '.join(note)))
        hapax.append((n, t, ch, typ, plug, rows, learned))

    taken_cc = {(e['mapping']['channel'], e['mapping']['data1']) for e in new}
    taken_tg = {(td['track'], td['parameter'], td['instrumentIndex']) for e in new for td in e['control']['targetData']}
    kept, dropped = [], 0
    for e in data.get('midiLearnSettings', {}).get('controls', []):
        m, tds = e.get('mapping', {}), e.get('control', {}).get('targetData', [])
        if (m.get('channel'), m.get('data1')) in taken_cc or m.get('data1') in JUNK_CCS or \
                any((td.get('track'), td.get('parameter'), td.get('instrumentIndex')) in taken_tg for td in tds):
            dropped += 1
        else:
            kept.append(e)
    data.setdefault('midiLearnSettings', {})['controls'] = kept + new

    if os.path.isdir(src_pd) and not os.path.exists(dst_pd):
        shutil.copytree(src_pd, dst_pd)
    save(dst, hdr, j)
    _, back = load(dst)
    ok = back == json.loads(json.dumps(j))
    for n, nm, ch, note in report:
        log(f'{n:>3} {nm[:28]:28} ch {ch!s:>4}  {note}')
    log(f'learn entries: {len(new)} written, {len(kept)} of yours kept, {dropped} replaced/removed')
    log(f'wrote {dst} - verify re-read: {"OK" if ok else "MISMATCH"}')
    defs = write_hapax_defs(name, hapax, src_pd, log) if write_defs else []
    return {'dst': dst, 'ok': ok, 'entries': len(new), 'kept': len(kept), 'dropped': dropped, 'defs': defs, 'name': name}

def write_hapax_defs(name, hapax, project_data, log=print):
    out_root = os.path.join(paths.data_dir(), 'Projects', mh.hx(name, 60))
    sd = os.path.join(paths.data_dir(), 'SD-Card', 'HAPAX')
    os.makedirs(out_root, exist_ok=True); os.makedirs(sd, exist_ok=True)
    prefix = mh.hx(name, 10)
    wavs = {}
    if os.path.isdir(project_data):
        for dp, _, fns in os.walk(project_data):
            for fn in fns:
                if fn.lower().endswith('.wav'):
                    wavs.setdefault(os.path.splitext(fn)[0].lower(), os.path.join(dp, fn))
    sheet = [f'# {name} - Hapax map', '', '| Ch | MPC track | Pots 1-8 | Other mapped (CC) | Pre-learned |', '|---|---|---|---|---|']
    written = []
    for n, t, ch, typ, plug, rows, learned in hapax:
        label = mh.hx(plug or mh.short_name(t.get('program', {}).get('name') or t['name']), 16) or f'Track {n}'
        fname = mh.hx(f'{prefix} CH{ch:02d} {label}', 60)
        path = os.path.join(out_root, fname + '.txt')
        vol_pan = [(7, 'Track Vol'), (10, 'Track Pan')]
        header = [f'Project {name} - MPC track {n} ({t["name"]})', f'port USBD ch {ch}']
        if typ == 0:
            prog = mh.read_track_data(t)
            if prog.get('kind') != 'drum' or not prog.get('pads'):
                continue
            sounds = mh.build_sounds(prog, lambda s: wavs.get(s.lower()))
            lanes, used = mh.assign_lanes(sounds)[0], {}
            lane_names = []
            for s in lanes:
                nm = mh.lane_label(s, 16); used[nm] = used.get(nm, 0) + 1
                lane_names.append((s['note'], nm if used[nm] == 1 else mh.hx(f'{nm[:14]} {used[nm]}', 16)))
            mh.write_def(path, label, 'DRUM', 'USBD', ch, lane_names,
                         [f'Project {name}', f'MPC track {n} {t["name"]}', 'Notes from this project s own pad map',
                          'Pots 1-2 track Volume Pan'], header, ccs=vol_pan, pots=[(1, 7), (2, 10)])
            sheet.append(f'| {ch} | {n} {t["name"]} (drums) | Volume, Pan | - | yes |')
        else:
            pots = sorted((x for x in rows if x.get('pot')), key=lambda x: x['pot'])
            ccs = [(x['cc'], x['label']) for x in sorted(rows, key=lambda x: x['cc'])] + vol_pan
            assign = [(x['pot'], x['cc']) for x in pots] or [(1, 7), (2, 10)]
            comment = [f'Project {name}', f'MPC track {n} {t["name"]}'] + \
                      [f'Pot {x["pot"]} CC{x["cc"]} {x["label"]}' for x in pots] + \
                      [f'{len(rows)} params mapped - pre-learned' if learned else
                       f'{len(rows)} params named - learn them by hand on the MPC' if rows else 'CC 7 Volume CC 10 Pan']
            mh.write_def(path, label, 'POLY', 'USBD', ch, [], comment, header, ccs=ccs, pots=assign, auto_lanes=bool(rows))
            others = ', '.join(f'{x["label"]} ({x["cc"]})' for x in rows if not x.get('pot'))
            sheet.append(f'| {ch} | {n} {t["name"]} ({plug or "keygroup"}) | {", ".join(x["label"] for x in pots) or "Volume, Pan"} | '
                         f'{others or "-"} | {"yes" if learned else ("NO - learn by hand" if rows else "vol/pan")} |')
        errs = mh.validate(path)
        shutil.copyfile(path, os.path.join(sd, fname + '.txt'))
        written.append((path, errs))
    open(os.path.join(out_root, 'MAP.md'), 'w', encoding='utf-8').write('\n'.join(sheet) + '\n')
    bad = [p for p, e in written if e]
    log(f'Hapax files: {len(written)} written to {out_root} (+ SD-Card\\HAPAX), validation errors: {len(bad)}')
    for p, e in written:
        if e: log(f'  FAIL {os.path.basename(p)}: {e}')
    return [p for p, _ in written]

def parse_overrides(s):
    out = {}
    for part in filter(None, (p.strip() for p in (s or '').split(','))):
        k, _, v = part.rpartition('=')
        out[k.strip()] = int(v)
    return out

if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=['list', 'map']); ap.add_argument('project')
    ap.add_argument('--name'); ap.add_argument('--channels', default='')
    ap.add_argument('--drum-channel', type=int, default=10)
    ap.add_argument('--no-defs', action='store_true')
    a = ap.parse_args()
    ov = parse_overrides(a.channels)
    if a.cmd == 'list':
        for r in analyze(a.project, ov, a.drum_channel)['tracks']:
            print(f'{r["n"]:>3} {r["track"][:28]:28} {r["type"]:9} {str(r["plugin"] or "")[:16]:16} ch {r["channel"]!s:>4} '
                  f'{"" if not r["plugin"] else ("pre-learn OK" if r["trusted"] else "learn by hand")}')
    else:
        try:
            map_project(a.project, a.name, ov, a.drum_channel, write_defs=not a.no_defs)
        except FileExistsError as e:
            sys.exit(str(e))
