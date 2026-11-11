"""
mpc_template.py - read an MPC 3 "probe" project and prepare the Hapax template.

  py -I mpc_template.py inspect "<MPC User drive>\\MPC Documents\\Projects\\HAPAX PROBE.xpj"
  py -I mpc_template.py sheet   "<MPC User drive>\\MPC Documents\\Projects\\HAPAX PROBE.xpj"
(Superseded by mpc_map.py / the Hapax Mapper app; kept for the fixed 16-track template.)

inspect : lists every track (type, plugin, MIDI input port/channel), the plugin parameter lists the MPC wrote
          into the project, and any MIDI Learn entries (midiLearnSettings) - the sample needed to write the
          template's learned CCs automatically.
sheet   : writes a per-track MIDI Learn sheet: Hapax pot -> CC -> exact MPC parameter (manual-learn fallback).

Read-only on the project. Writing the finished template is a separate step added once a real MIDI Learn
sample exists, so the format is copied from the MPC rather than guessed.
"""
import argparse, json, os, sys, zlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hapax_integration as hi

TRACK_TYPES = {0: 'Drum', 1: 'Keygroup', 3: 'Plugin', 4: 'MIDI', 7: 'Return', 8: 'Submix', 9: 'Output'}  # seen in MPC 3.10 projects

def load(p):
    b = open(p, 'rb').read(); pos, out = 0, b''
    while pos < len(b) and b[pos:pos + 2] == b'\x1f\x8b':
        d = zlib.decompressobj(31); out += d.decompress(b[pos:]); pos = len(b) - len(d.unused_data)
    i = out.find(b'{')
    return out[:i].decode('ascii', 'replace').split('\n'), json.loads(out[i:])

def tracks(j):
    for n, t in enumerate(j['data'].get('tracks', []), 1):
        prog = t.get('program', {})
        desc = prog.get('plugin', {}).get('plugin', {}).get('description') or {}
        route = t.get('midiInputRoute', {})
        yield n, t, prog.get('type'), desc.get('name'), route

def inspect(path):
    hdr, j = load(path)
    print(f'header: {hdr[:3]}')
    print(f'{"#":>3} {"track name":24} {"type":9} {"plugin":18} MIDI input (port, channel)')
    for n, t, typ, plug, route in tracks(j):
        port = route.get('inputPort', {})
        ch = route.get('inputChannel')
        print(f'{n:>3} {str(t.get("name"))[:24]:24} {TRACK_TYPES.get(typ, typ)!s:9} {str(plug or "")[:18]:18} '
              f'{port.get("deviceName")!r} id={port.get("deviceId")!r} ch={"All" if ch == 0 else ch}')
    params = hi.plugin_params_from_project(j)
    print('\nplugin parameter lists captured:', {k: len(v) for k, v in params.items()})
    ml = j['data'].get('midiLearnSettings', {})
    ctl = ml.get('controls', [])
    print(f'\nmidiLearnSettings.controls: {len(ctl)} entries')
    for c in ctl[:6]:
        print('  ', json.dumps(c)[:1500])
    hapax = [r.get('inputPort', {}) for _, _, _, _, r in tracks(j) if 'hapax' in str(r.get('inputPort', {}).get('deviceName', '')).lower()]
    print('\nHapax port as the MPC names it:', hapax[0] if hapax else 'NOT FOUND - set track 1 MIDI input to the Hapax and save')

def sheet(path, out):
    _, j = load(path)
    params = hi.plugin_params_from_project(j)
    lines = ['# MIDI Learn sheet (Hapax pots -> MPC parameters)', '',
             'For each track: MIDI Learn -> LEARN -> + -> Source = that track\'s program -> Target = the parameter below,',
             'then on the Hapax track (same number) open Autom, select the CC lane and press 2ND + Ping.', '']
    for ch, label, kind, plug in hi.CHANNEL_PLAN:
        lines.append(f'## Track {ch} - {label} (channel {ch})')
        if plug:
            ps = params.get(plug)
            if not ps:
                lines += [f'_{plug} not found in the probe project - load it on track {ch} and re-save._', '']
                continue
            lines += ['| Hapax pot | CC | MPC parameter |', '|---|---|---|']
            for i, (lbl, cc, idx, name) in enumerate(hi.resolve_pots(kind, plug, ps), 1):
                lines.append(f'| {i} | {cc} | {name or "(no match - pick one)"} |')
        lines += ['', f'Mixer: CC 7 -> track {ch} Volume, CC 10 -> Pan, CC 28-31 -> Send 1-4', '']
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    open(out, 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
    print(f'wrote {out}')

PLUGIN_PARAM_BASE = 4096      # MIDI Learn targetData.parameter = 4096 + plugin automationIndex (verified: Jura VCF Cutoff 19 -> 4115)
# Plugin output-level parameters CC 7 may target. Not 'amp gain' / 'amp level': on Odyssey, Amp Gain is the
# VCA bias (opens the amp = constant drone), which caused a stuck tone in the first template.
VOLUME_NAMES = ('volume', 'gbl vol', 'global vol', 'global level', 'level')

MIXER_INSTRUMENT = 257        # track channel strip (MPC's own Q-Link targets: parameter 7 = volume, 10 = pan)
MIXER_PARAMS = {7: (7, 'volume', 'Volume'), 10: (10, 'pan', 'Pan')}   # cc -> (parameter, mixable key, label)

MONITOR_MERGE = 3   # midiMonitorable.state: Auto = 2, Merge = 3 (verified in HAPAX PROBE 3)

def hapax_port_from(project):
    """The MPC's own saved inputPort entry for the Hapax (first track whose input port name contains HAPAX)."""
    _, pj = load(project)
    for t in pj['data'].get('tracks', []):
        port = t.get('midiInputRoute', {}).get('inputPort', {})
        if 'hapax' in str(port.get('deviceName', '')).lower():
            return dict(port)
    sys.exit(f'no track with a HAPAX input port in {project}')

def build(probe, name, port_from=None):
    """Write <name>.xpj next to the probe. Starts from the probe and sets:
      - every plan track's MIDI channel (plugin tracks: midiOutputRoute.outputChannel = ch-1;
        drum/keygroup tracks: midiInputRoute.inputChannel = ch)  [both verified in HAPAX PROBE 2]
      - pots 1-8 for plugins whose saved state decodes cleanly, controlValue = the knob's current value
      - CC 7 / CC 10 -> track volume / pan on every plan track, controlValue = current fader / pan
    Entry shape is copied from the probe's own learned plugin CC. Replaces the probe's learn list. Never overwrites."""
    import copy, gzip, shutil
    hdr, j = load(probe)
    data = j['data']
    tmpl = next((c for c in data['midiLearnSettings']['controls']
                 if c['control']['targetData'][0].get('parameter', 0) >= PLUGIN_PARAM_BASE
                 and c['mapping'].get('data1') not in (120, 121, 123)), None)
    if tmpl is None:
        sys.exit('no usable learned plugin-parameter sample in the probe')
    params = hi.plugin_params_from_project(j)
    all_tracks = list(tracks(j))
    by_plugin = {plug: t for n, t, typ, plug, route in reversed(all_tracks) if plug}
    drums = [t for n, t, typ, plug, route in all_tracks if typ == 0]
    keygroups = [t for n, t, typ, plug, route in all_tracks if typ == 1]

    def entry(track_name, ch, cc, parameter, instrument, label, value):
        e = copy.deepcopy(tmpl)
        e['control']['name'] = f'{track_name} ({label})'
        td = e['control']['targetData'][0]
        td.update({'parameter': parameter, 'track': track_name, 'instrumentIndex': instrument})
        e['control']['controlValue'] = float(value)
        e['mapping'].update({'channel': ch, 'data1': cc})
        return e

    controls, report = [], []
    kg_iter = iter(keygroups)
    for ch, label, kind, plug in hi.CHANNEL_PLAN:
        if plug:
            t = by_plugin.get(plug)
        elif kind == 'drum':
            t = drums[0] if drums else None
        else:
            t = next(kg_iter, None)
        if t is None:
            report.append(f'ch {ch:>2} {label}: no matching track - skipped'); continue
        if plug:
            t['midiOutputRoute']['outputChannel'] = ch - 1     # main-panel "MIDI CH" field (kept as in TEMPLATE 2)
        t['midiInputRoute']['inputChannel'] = ch               # Track Settings -> INPUT CHANNEL (1-based, 0 = All)
        if port_from:
            t['midiInputRoute']['inputPort'] = dict(port_from)  # Track Settings -> INPUT PORT = the Hapax
            t.setdefault('midiMonitorable', {})['state'] = MONITOR_MERGE
        note = []
        if plug:
            vals = hi.plugin_param_values(t)
            pots = [(cc, idx, pname) for _, cc, idx, pname in hi.resolve_pots(kind, plug, params.get(plug, [])) if idx is not None]
            # trust the decoded layout only if EVERY parameter the MPC lists decodes to a normalized 0..1 value
            ok = bool(vals) and all(i in vals and 0.0 <= vals[i] <= 1.0 for i, _ in params.get(plug, []))
            if ok:
                for cc, idx, pname in pots:
                    controls.append(entry(t['name'], ch, cc, PLUGIN_PARAM_BASE + idx, 256, pname, vals[idx]))
                note.append(f'{len(pots)} pots')
            else:
                note.append('pots NOT written (plugin state not decodable) - learn by hand')
        mix = t.get('program', {}).get('mixable', {})
        for cc, (param, key, lbl) in MIXER_PARAMS.items():
            controls.append(entry(t['name'], ch, cc, param, MIXER_INSTRUMENT, lbl, mix.get(key, 0.5)))
        note.append('vol/pan')
        report.append(f'ch {ch:>2} {label:15} track "{t["name"]}": ' + ', '.join(note))
    data['midiLearnSettings']['controls'] = controls

    proj_dir = os.path.dirname(os.path.abspath(probe))
    dst = os.path.join(proj_dir, name + '.xpj')
    src_pd = os.path.splitext(os.path.abspath(probe))[0] + '_[ProjectData]'
    dst_pd = os.path.join(proj_dir, name + '_[ProjectData]')
    if os.path.exists(dst):
        sys.exit(f'refusing to overwrite {dst}')
    body = '\n'.join(hdr[:5]) + '\n' if len(hdr) >= 5 else '\n'.join(hdr) + '\n'
    # MPC 3 writes JSON with a newline per element and no indentation; json indent=0 reproduces that layout
    raw = body.encode('ascii') + json.dumps(j, indent=0).encode('utf-8')
    if os.path.isdir(src_pd) and not os.path.exists(dst_pd):
        shutil.copytree(src_pd, dst_pd)
    with open(dst, 'wb') as f:
        f.write(gzip.compress(raw, compresslevel=6))
    # verify: re-read and compare everything except the learn list
    hdr2, j2 = load(dst)
    a = json.loads(json.dumps(j)); b = j2
    ok = a == b and hdr2[:3] == hdr[:3]
    print('\n'.join(report))
    print(f'\nwrote {dst} ({len(controls)} MIDI Learn entries) - verify re-read: {"OK" if ok else "MISMATCH"}')
    print(f'copied {src_pd} -> {dst_pd}' if os.path.isdir(dst_pd) else 'no ProjectData folder to copy')

if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=['inspect', 'sheet', 'build']); ap.add_argument('project')
    import paths
    ap.add_argument('--out', default=os.path.join(paths.data_dir(), 'Reports', 'midi-learn-sheet.md'))
    ap.add_argument('--name', default='HAPAX TEMPLATE')
    ap.add_argument('--port-from', help='project whose saved HAPAX input port is copied to every plan track (+ Merge)')
    a = ap.parse_args()
    {'inspect': lambda: inspect(a.project), 'sheet': lambda: sheet(a.project, a.out),
     'build': lambda: build(a.project, a.name, hapax_port_from(a.port_from) if a.port_from else None)}[a.cmd]()
