"""
Shared Hapax <-> MPC integration plan: channel plan, CC numbers, pot layout, parameter matching.

Edit CHANNEL_PLAN to change which instrument lives on which channel/track; rerun mpc_hapax.py and
mpc_template.py afterwards so the Hapax definitions and the MPC template stay in step.
"""
import json, os, re

# Hapax track N <-> MPC track N <-> MIDI channel N (port USBD).
# kind: synth | keys | drum | keygroup   plugin: MPC plugin display name (None for drum/keygroup tracks)
CHANNEL_PLAN = [
    (1, 'Jura', 'synth', 'Jura'),
    (2, 'Mini D', 'synth', 'Mini D'),
    (3, 'Odyssey', 'synth', 'Odyssey'),
    (4, 'TubeSynth', 'synth', 'TubeSynth'),
    (5, 'Bassline', 'synth', 'Bassline'),
    (6, 'OPx-4', 'synth', 'OPx-4'),
    (7, 'Stage Piano', 'keys', 'Stage Piano'),
    (8, 'Stage EP', 'keys', 'Stage EP'),
    (9, 'Organ', 'keys', 'Organ'),
    (10, 'Drums', 'drum', None),
    (11, 'Studio Strings', 'keys', 'Studio Strings'),
    (12, 'Fabric XL', 'keys', 'Fabric XL'),
    (13, 'Hype', 'synth', 'Hype'),
    (14, 'Keygroup A', 'keygroup', None),
    (15, 'Keygroup B', 'keygroup', None),
    (16, 'Keygroup C', 'keygroup', None),
]

# Which pot layout each MPC plugin gets (by the plugin's display name). Unknown plugins try the synth layout
# and only get pots if at least MIN_POT_MATCHES parameters match.
PLUGIN_KINDS = {
    'Jura': 'synth', 'Mini D': 'synth', 'Odyssey': 'synth', 'TubeSynth': 'synth', 'Bassline': 'synth',
    'OPx-4': 'synth', 'Hype': 'synth', 'Sub Factory': 'synth', 'Iona': 'synth', 'Ring The Alarm': 'synth',
    'Stage Piano': 'keys', 'Stage EP': 'keys', 'Organ': 'keys', 'Studio Strings': 'keys', 'Fabric XL': 'keys',
    'Fabric': 'keys', 'Fabric Piano': 'keys', 'Fabric Electric Piano': 'keys', 'Fabric Select': 'keys',
    'Electric': 'keys', 'Mellotron': 'keys', 'Solina': 'keys',
}
MIN_POT_MATCHES = 4

POT_CCS = [20, 21, 22, 23, 24, 25, 26, 27]
# CCs for the other 24 mapped parameters: MIDI-spec "undefined" controllers only (no mod wheel, volume, pan,
# expression, sustain, bank select, data entry, NRPN/RPN or channel-mode messages).
CC_POOL = [3, 9, 14, 15, 28, 29, 30, 31, 85, 86, 87, 88, 89, 90] + list(range(102, 120))
MAX_PARAMS = 32          # Hapax pots 1-8 (MIDI "undefined" range 20-31)
MIXER_CCS = [(7, 'Track Vol'), (10, 'Track Pan')]   # track fader + pan (sends not mapped: no verified target)

# Pot roles: (label shown on the Hapax, regexes tried in order against MPC plugin parameter names)
SYNTH_POTS = [
    ('Cutoff',     [r'^(vcf |filter |flt )?(cutoff|cut off|freq|frequency)$', r'cutoff', r'vcf.*freq', r'filter.*(freq|cut)', r'^freq']),
    ('Resonance',  [r'^(vcf |filter |flt )?(reso|resonance|res|emphasis|q)$', r'reso', r'emphasis']),
    ('Filter Env', [r'(vcf|filter|flt).*(env|eg).*(amt|amount|depth|mod|int)', r'^env (amt|amount|depth)', r'(vcf|filter) env$', r'env.*(vcf|filter)']),
    ('Attack',     [r'^(amp |vca |env |eg )?(attack|att|a)$', r'(amp|vca).*attack', r'attack']),
    ('Decay',      [r'^(amp |vca |env |eg )?(decay|dec|d)$', r'(amp|vca).*decay', r'decay']),
    ('Sustain',    [r'^(amp |vca |env |eg )?(sustain|sus|s)$', r'(amp|vca).*sustain', r'sustain']),
    ('Release',    [r'^(amp |vca |env |eg )?(release|rel|r)$', r'(amp|vca).*release', r'release']),
    ('LFO Rate',   [r'^lfo ?1? ?(rate|speed|freq)', r'lfo.*(rate|speed)', r'^(mod )?rate$']),
]
KEYS_POTS = [
    ('Tone',       [r'^(cutoff|tone|bright|brightness|timbre)$', r'^(filter )?cutoff', r'tone', r'bright', r'^eq high$']),
    ('Drive',      [r'^(drive|overdrive|dist|distortion|saturation)$', r'^amp drive$', r'drive', r'dist']),
    ('Mod Depth',  [r'^trem(olo)? depth$', r'^chorus mix$', r'^rotary mix$', r'^(scan/vib|vibrato)( depth)?$', r'^phaser mix$', r'(trem|chorus|vibrato|phaser|rotary).*(depth|mix)']),
    ('Mod Rate',   [r'^trem(olo)? rate$', r'^chorus rate$', r'^rotary speed$', r'^scan/vib rate$', r'^phaser rate$', r'(trem|chorus|vibrato|phaser|rotary).*(rate|speed)']),
    ('Delay Mix',  [r'^(del|delay) (mix|amt|amount|level)$', r'delay.*(mix|level)', r'del mix']),
    ('Reverb Mix', [r'^(rev|reverb) (mix|amt|amount|level)$', r'reverb.*(mix|level)', r'rev mix']),
    ('Attack',     [r'^(amp |vca |env )?(attack|att)$', r'^attack']),
    ('Release',    [r'^(amp |vca |env )?(release|rel)$', r'^release']),
]
# Organ: drawbars are the instrument, so pots 1-8 = the first 8 drawbars as the MPC names them.
ORGAN_POTS = [(f'Drawbar {i}', [rf'^db {n}\s*$']) for i, n in enumerate(['16', '5 1/3', '8', '4', '2 2/3', '2', '1 3/5', '1 1/3'], 1)]

# Hand-picked pots (exact MPC parameter names from the HAPAX PROBE project, MPC 3.10) where pattern
# matching is not good enough. Each entry: (Hapax label, exact MPC parameter name).
OVERRIDES = {
    'Mini D': [('Cutoff', 'LPF Cutoff'), ('Resonance', 'LPF Reso'), ('Filter Env', 'LPF Contour Amount'),
               ('Attack', 'Amp Attack'), ('Decay', 'Amp Decay'), ('Sustain', 'Amp Sustain'),
               ('Release', 'Amp Release'), ('LFO Rate', 'Lfo Speed')],
    'Odyssey': [('Cutoff', 'Low Pass Filter Volts'), ('Resonance', 'Low Pass Filter Reso'),
                ('Filter Env', 'Filter CV 3 Level'), ('Attack', 'ADSR Attack'), ('Decay', 'ADSR Decay'),
                ('Sustain', 'ADSR Sustain'), ('Release', 'ADSR Release'), ('LFO Rate', 'LFO Speed')],
    'TubeSynth': [('Cutoff', 'LPF Cutoff'), ('Resonance', 'LPF Reso'), ('Filter Env', 'LPF Env'),
                  ('Attack', 'Amp Attack'), ('Decay', 'Amp Decay'), ('Sustain', 'Amp Sustain'),
                  ('Release', 'Amp Release'), ('LFO Rate', 'LFO 1 Rate')],
    'Bassline': [('Cutoff', 'LP Cutoff'), ('Resonance', 'Reso'), ('Env Mod', 'Filter Env'),
                 ('Decay', 'Filter Decay'), ('Amp Decay', 'Amp Decay'), ('Drive', 'Drive'),
                 ('Glide', 'Glide Time'), ('Boost', 'Boost')],
    'OPx-4': [('Cutoff', 'Cutoff1'), ('FM Amount', 'FM Scaling'), ('Op2 Level', 'Level2'),
              ('Attack', 'Env Attack Scale'), ('Decay', 'Env Decay1 Scale'), ('Sustain', 'Env Sustain Scale'),
              ('Release', 'Env Release Scale'), ('LFO Rate', 'LFO1 Speed')],
    'Stage Piano': [('Lid', 'Lid'), ('Hammer', 'Hammer'), ('Dynamics', 'Dynamics'), ('Age', 'Age'),
                    ('Delay Mix', 'Del Mix'), ('Reverb Mix', 'Reverb Mix'), ('Hard Attack', 'Hard Attack'),
                    ('Release', 'Release')],
    'Studio Strings': [('Cutoff', 'Filter Cutoff'), ('Dynamics', 'Dynamics'), ('Vibrato', 'MW Vibrato'),
                       ('Vib Rate', 'Vibrato Speed'), ('Delay Mix', 'Del Mix'), ('Reverb Mix', 'Reverb Mix'),
                       ('Attack', 'Attack'), ('Release', 'Release')],
}

def pots_for(kind, plugin):
    if plugin == 'Organ':
        return ORGAN_POTS
    return KEYS_POTS if kind == 'keys' else SYNTH_POTS

def resolve_pots(kind, plugin, params):
    """params: list of (automationIndex, name). Returns list of 8 (label, cc, automationIndex|None, paramName|None)."""
    if plugin in OVERRIDES:
        by_name = {n.strip().lower(): (i, n.strip()) for i, n in params}
        res = []
        for (label, pname), cc in zip(OVERRIDES[plugin], POT_CCS):
            hit = by_name.get(pname.lower())
            res.append((hit[1] if hit else label, cc, hit[0] if hit else None, hit[1] if hit else None))
        return res
    out, used = [], set()
    for (label, rxs), cc in zip(pots_for(kind, plugin), POT_CCS):
        hit = None
        for rx in rxs:
            for idx, name in params:
                if idx in used:
                    continue
                n = name.strip().lower()
                if not re.search(rx, n):
                    continue
                # keep envelope/filter pots off LFO, velocity, keytrack and per-layer "perc"/"comp" copies
                if label not in ('LFO Rate', 'Mod Rate', 'Mod Depth') and re.search(r'lfo|velo|key ?track|kbd|pitch|perc |comp |reverb |del |delay ', n) \
                        and label not in ('Delay Mix', 'Reverb Mix'):
                    continue
                hit = (idx, name.strip()); break
            if hit:
                break
        if hit:
            used.add(hit[0])
        out.append((hit[1] if hit else label, cc, hit[0] if hit else None, hit[1] if hit else None))
    return out

_JUCE_B64 = '.ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+'

def juce_b64(s):
    """Decode JUCE MemoryBlock::toBase64Encoding ('<size>.<chars>', 6 bits per char, LSB-first)."""
    size_s, _, data = s.partition('.')
    out = bytearray(int(size_s)); pos = 0
    for ch in data:
        v = _JUCE_B64.index(ch)
        for bit in range(6):
            if v & (1 << bit):
                byte, b = divmod(pos + bit, 8)
                if byte < len(out):
                    out[byte] |= 1 << b
        pos += 6
    return bytes(out)

STATE_HEADER = 80   # 'ACVS' + 4 zero bytes + 72-byte plugin name; then one float32 per automationIndex

def plugin_param_values(track):
    """{automationIndex: current normalized value} decoded from a plugin track's saved state, or {} if the layout
    doesn't look right (header must be 'ACVS')."""
    import struct
    st = track.get('program', {}).get('plugin', {}).get('plugin', {}).get('state')
    if not isinstance(st, str) or '.' not in st:
        return {}
    raw = juce_b64(st)
    if raw[:4] != b'ACVS':
        return {}
    n = (len(raw) - STATE_HEADER) // 4
    return {i: struct.unpack_from('<f', raw, STATE_HEADER + 4 * i)[0] for i in range(n)}

# Plugins whose saved state did not decode consistently across MPC saves of the same preset (HAPAX PROBE vs
# HAPAX PROBE 3): their pots are never pre-learned, whatever one particular save looks like.
STATE_UNTRUSTED = {'Odyssey', 'Fabric XL', 'Hype'}

def state_is_plausible(vals, params):
    """Trust decoded values only if every listed parameter is a normalized 0..1 float AND the set looks like a
    real patch (not mostly zeros, several distinct values). Hype's state decodes to all zeros - rejected."""
    if not vals or not params:
        return False
    xs = [vals.get(i) for i, _ in params]
    if any(x is None or not (0.0 <= x <= 1.0) for x in xs):
        return False
    zeros = sum(1 for x in xs if x == 0.0)
    return zeros / len(xs) < 0.7 and len({round(x, 4) for x in xs}) >= 4

def qlink_ordered_params(track):
    """Unique (automationIndex, name, 'page sub knob') for a plugin track, in the MPC's own Q-Link page order."""
    rows = []
    for m in track.get('program', {}).get('customisable', {}).get('mapping', []):
        try:
            key = tuple(int(x) for x in str(m.get('parameterIndex', '')).split())
        except ValueError:
            key = (999,)
        rows.append((key, m.get('automationIndex'), (m.get('name') or '').strip(), m.get('parameterIndex', '')))
    rows.sort(key=lambda r: r[0])
    seen, out = set(), []
    for _, idx, name, pos in rows:
        if idx is None or idx in seen:
            continue
        seen.add(idx); out.append((idx, name, pos))
    return out

def hapax_label(name):
    """Hapax names: alphanumeric ASCII plus ' ', '_', '-', '+' (Squarp template); keep them short."""
    s = name.replace('#', 's').replace('&', ' and ').replace('/', '-').replace('.', ' ')
    s = re.sub(r'[^A-Za-z0-9 _+\-]', ' ', s)
    return re.sub(r'\s+', ' ', s).strip(' -_')[:24] or 'Param'

def assign_ccs(rows):
    """rows: list of dicts with 'pot' (1-8 or None). Pots get CC 20-27 by pot number, the rest CC_POOL in order."""
    pool = iter(CC_POOL)
    for r in rows:
        r['cc'] = POT_CCS[r['pot'] - 1] if r.get('pot') else next(pool)
    return rows

def default_selection(kind, plugin, ordered):
    """ordered: qlink_ordered_params(). Default = the 8 pot parameters + the first unique Q-Link-page parameters, 32 total."""
    params = [(i, n) for i, n, _ in ordered]
    pots = resolve_pots(kind, plugin, params)
    rows, used = [], set()
    for pot, (lbl, cc, idx, pname) in enumerate(pots, 1):
        if idx is not None:
            rows.append({'index': idx, 'name': pname, 'label': hapax_label(pname), 'pot': pot}); used.add(idx)
    for idx, name, _ in ordered:
        if len(rows) >= MAX_PARAMS:
            break
        if idx not in used:
            rows.append({'index': idx, 'name': name, 'label': hapax_label(name), 'pot': None}); used.add(idx)
    return assign_ccs(rows)

def plugin_selection(kind, plugin, ordered, saved=None):
    """The 32 parameters for a plugin: the user's saved choice (plugin_maps.json in the data folder) if it still matches this
    plugin's parameters, else the default. Returns rows: {index, name, label, pot, cc}."""
    names = {i: n for i, n, _ in ordered}
    if saved:
        rows = [{'index': r['index'], 'name': names[r['index']], 'label': hapax_label(r.get('label') or names[r['index']]),
                 'pot': r.get('pot')} for r in saved.get('params', []) if r.get('index') in names][:MAX_PARAMS]
        if rows:
            return assign_ccs(rows)
    return default_selection(kind, plugin, ordered)

import paths as _paths
MAPS_FILE = os.path.join(_paths.data_dir(), 'plugin_maps.json')   # your saved parameter choices (per plugin)

def load_maps():
    try:
        return json.load(open(MAPS_FILE, encoding='utf-8'))
    except (OSError, ValueError):
        return {}

def save_maps(maps):
    with open(MAPS_FILE, 'w', encoding='utf-8') as f:
        json.dump(maps, f, indent=2)

def plugin_params_from_project(project_json):
    """{plugin display name: [(automationIndex, name), ...]} from MPC project plugin tracks."""
    res = {}
    for t in project_json.get('data', project_json).get('tracks', []):
        prog = t.get('program', {})
        desc = prog.get('plugin', {}).get('plugin', {}).get('description') or {}
        name = desc.get('name')
        if not name:
            continue
        seen, params = set(), []
        for m in prog.get('customisable', {}).get('mapping', []):
            idx = m.get('automationIndex')
            if idx is None or idx in seen:
                continue
            seen.add(idx); params.append((idx, m.get('name', '')))
        res.setdefault(name, params)
    return res
