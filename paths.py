"""
Where things live. Nothing here depends on drive letters.

  CODE_DIR    this folder (the tool)
  RESOURCES   format samples saved by an MPC (Hapax input port, one learned MIDI-Learn entry)
  data_dir()  where generated files go (Hapax definitions, reports, mapped-project Hapax files, your
              parameter choices). Order: env var HAPAX_MPC_DATA, then settings.json {"data_dir": ...} in
              this folder, then %USERPROFILE%\\Documents\\Hapax-MPC-Mappings.
  mpc_drives() the MPC's drives found by volume NAME ("MPC Content", "MPC User"), whatever letters Windows
              gave them. The MPC must be in Controller Mode and connected by USB.
"""
import json, os, string

CODE_DIR = os.path.dirname(os.path.abspath(__file__))
RESOURCES = os.path.join(CODE_DIR, 'resources')
SETTINGS = os.path.join(CODE_DIR, 'settings.json')
MPC_LABELS = ('MPC Content', 'MPC User')

def data_dir():
    d = os.environ.get('HAPAX_MPC_DATA')
    if not d and os.path.isfile(SETTINGS):
        try:
            d = json.load(open(SETTINGS, encoding='utf-8')).get('data_dir')
        except (OSError, ValueError):
            d = None
    d = d or os.path.join(os.path.expanduser('~'), 'Documents', 'Hapax-MPC-Mappings')
    os.makedirs(d, exist_ok=True)
    return d

def volume_label(root):
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(261)
        ok = ctypes.windll.kernel32.GetVolumeInformationW(ctypes.c_wchar_p(root), buf, 261, None, None, None, None, 0)
        return buf.value if ok else ''
    except (AttributeError, OSError):
        return ''

def mpc_drives():
    """{'MPC Content': 'X:\\', 'MPC User': 'Y:\\'} for whichever of the MPC's drives are mounted."""
    found = {}
    for letter in string.ascii_uppercase:
        root = f'{letter}:\\'
        if os.path.exists(root):
            lbl = volume_label(root)
            if lbl in MPC_LABELS:
                found[lbl] = root
    return found

def mpc_projects_dir():
    user = mpc_drives().get('MPC User')
    p = os.path.join(user, 'MPC Documents', 'Projects') if user else None
    return p if p and os.path.isdir(p) else None

def removable_drives():
    out = []
    try:
        import ctypes
        for letter in string.ascii_uppercase:
            root = f'{letter}:\\'
            if os.path.exists(root) and ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(root)) == 2:
                out.append(root)
    except (AttributeError, OSError):
        pass
    return out
