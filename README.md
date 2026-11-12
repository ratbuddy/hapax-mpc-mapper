# Hapax Mapper

Maps an MPC 3 project to a Squarp Hapax. It does three things:

- sets up MIDI routing on the MPC tracks;
- pre-learns the MPC's MIDI Learn entries for plugin parameters;
- writes a matching Hapax instrument definition for each track.

It runs on Windows with Python 3 (`py`/`pyw` launcher) and needs no extra packages.

## Workflow

| # | Where | Step |
|---|-------|------|
| 1 | MPC | Make a new project, add tracks and plugins, then **Save** |
| 2 | MPC | Menu → **Controller Mode** (USB to the PC). Its drives mount by name, so any drive letter works |
| 3 | PC | Run `Hapax Mapper.cmd`, click **Open…**, and pick the project from `MPC Documents\Projects` |
| 4 | PC | Optional: change a track's PORT or MIDI CH. Pick up to 32 parameters per plugin, set the 8 pots, and rename for the Hapax |
| 5 | PC | Click **MAP → MPC**. It writes `<name> HAPAX.xpj` next to the original and leaves the original untouched |
| 6 | PC | Put the Hapax SD card in a reader and click **Copy to SD card**. Files go to `<card>\HAPAX\` |
| 7 | MPC | Exit Controller Mode and load `<name> HAPAX` |
| 8 | Hapax | Load each track's instrument definition: `<project> CHnn <instrument>`, e.g. `Summer Jam CH01 Jura` (ports 2–16: `Summer Jam P2 CH01 Jura`) |

Parameter choices are saved per plugin. The next project that uses the same plugin starts with your picks.

## What a mapped project gets

| Item | Value |
|------|-------|
| Track Settings → Input port | `HAPAX MIDI 1` by default (so the MPC's own pads don't reach every track). Per track: `HAPAX MIDI 1`–`16` or `All Ports` |
| Track Settings → Input channel | channel from the app. The first drum track gets 10; other tracks take the lowest free channel, 1–16. A channel you set wins; automatic tracks move around it |
| Hapax definition → OUTPORT | `USBD` for port 1 and All Ports, `USBD2`–`USBD16` for ports 2–16 (the Hapax's USB virtual cables) |
| MIDI monitor | Merge |
| CC 7 / CC 10 | track volume / pan, on every mapped track |
| Plugin parameters | up to 32 per plugin, as MIDI Learn entries holding each knob's current value (loading the project changes nothing) |
| Hapax pot start values | each pot's `DEFAULT=` is that knob's (or fader's) value at mapping time, so the first turn doesn't jump the sound. ✎ by-hand plugins start at 0. Change a preset on the MPC later and the pots still start at the old values |
| Your own MIDI Learn entries | kept, unless one clashes on the same channel+CC or the same target |
| Drum tracks | Hapax drum lanes are named from the kit's pads |

## CC layout (per channel)

| Hapax control | CC | MPC target |
|---------------|----|------------|
| Pots 1–8 | 20–27 | the parameters marked POT 1–8 |
| Automation lanes 9–32 | 3, 9, 14, 15, 28–31, 85–90, 102–119 (in that order) | the other selected parameters |
| Track Vol | 7 | channel-strip volume |
| Track Pan | 10 | channel-strip pan |

CC 120–127 are never used. They are channel-mode messages; the Hapax Stop button sends All Notes Off (CC 123).

**Ports don't separate CCs.** An MPC MIDI Learn entry stores only channel + CC, never a port (checked in MPC-saved projects). Two tracks on the same channel share pots, lanes and Vol/Pan even on different ports; only their notes stay apart. Automatic channels are therefore unique across all ports, and the app marks a shared channel ⚠ in red.

## Plugins

| Status | Plugins | Meaning |
|--------|---------|---------|
| ✓ learned | Jura, Mini D, TubeSynth, Bassline, OPx-4, Stage Piano, Stage EP, Organ, Studio Strings | saved state decodes, so the parameters are pre-learned |
| ✎ by hand | Odyssey, Fabric XL, Hype | state isn't readable. CCs and names still go to the Hapax; MIDI-learn each one once on the MPC |
| other plugins | — | the app decodes the state and sanity-checks it; the track list shows which status each gets |

Default parameter order is the plugin's own Q-Link pages. For known plugins, the 8 pots are hand-picked (filter, resonance, envelope, LFO and so on).

## Files

| Path | What |
|------|------|
| `hapax_mapper.pyw` | the app (Tkinter) |
| `mpc_map.py` | engine: `py -I mpc_map.py list|map "<project.xpj>"` |
| `hapax_integration.py` | parameter selection, CC assignment, plugin state decoding |
| `mpc_hapax.py` | builds the full Hapax definition library from the MPC's drum kits and instruments |
| `mpc_template.py` | older fixed 16-track template builder (superseded by `mpc_map.py`) |
| `mpc_quarantine.py` | move/undo duplicate MPC files: `py -I mpc_quarantine.py undo <manifest.csv> [X:]`. Undo finds the MPC drive by volume name if its letter changed |
| `paths.py` | finds the MPC drives by volume name and the data folder |
| `resources/` | format samples taken from MPC-saved projects (Hapax input port, one MIDI Learn entry) |

## Data folder

Generated files never go into this repo. The data folder is resolved in this order:

1. env var `HAPAX_MPC_DATA`
2. `settings.json` here: `{"data_dir": "D:\\Somewhere"}` (git-ignored)
3. `%USERPROFILE%\Documents\Hapax-MPC-Mappings`

| Subfolder | Contents |
|-----------|----------|
| `plugin_maps.json` | your saved parameter choices per plugin |
| `Projects\<name>\` | the Hapax definitions plus a `MAP.md` CC sheet for each mapped project |
| `SD-Card\HAPAX\` | everything ever generated, ready to copy to a card |

## Verified on hardware (MPC Live III, MPC 3.10)

| Check | Status |
|-------|--------|
| Pots → plugin parameter (Jura, CC 20) | ✓ |
| CC 7 → track volume (Jura) | ✓ |
| Input port `HAPAX MIDI 1` + Merge; port survives a replug | ✓ |
| Mapped project: notes on `HAPAX MIDI 1` + the track's own channel (Stage Piano, ch 7); CC 7 → its Mixer fader | ✓ |
| CC 10 → pan | not yet tested |
| Input port `HAPAX MIDI 2`–`16` | not yet tested. The MPC entry is derived from port 1 (device ID `24-0` → `24-1`…); `All Ports` is copied from an MPC-saved project |
| Full 16-track mapped project loading all entries (~320) | not yet tested (104 tested) |
| Plugin pots while a *different* track is focused on the MPC | not yet tested (forum: plugin-target learns work out of focus, Q-Link learns don't; these are plugin-target learns) |
| Drum track + plugin playing the same note numbers on different channels | low risk: the forum's long-standing MPC note-off bug is reported fixed in MPC 3.6 (this setup runs 3.10). If notes still drop, move the kit's pads low or set key ranges |

`HAPAX MIDI 1` input-port settings on the MPC: **Track** and **Control** on, **Global** off. "Enable Mapping" (MIDI Learn) is an MPC setting, not saved in projects.

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| MIDI Monitor shows the Hapax's notes and CCs on `HAPAX MIDI 1`, but no track plays, no fader moves, and `HAPAX MIDI 1` is missing from a track's INPUT PORT list | `HAPAX MIDI 1` has Track/Control off. The Monitor ignores those settings; tracks and MIDI Learn don't. They are MPC-wide preferences, not stored in projects | Preferences → MIDI/Sync → Input Ports → `HAPAX MIDI 1`: Track on, Control on, Global off. Then re-pick `HAPAX MIDI 1` on any track you changed |
| CC 7 doesn't move the plugin's own volume knob | CC 7 targets the track's Mixer fader, not the plugin | Watch the Mixer |
| Copy to SD card says to map first | It copies the files MAP → MPC makes | Click MAP → MPC first |

## Not done (by choice)

| Item | State | What it would take |
|------|-------|--------------------|
| Drum and keygroup pots beyond Vol/Pan | Not built. Those parameters are adjusted on the MPC directly | Kit-wide pots, one learn entry targeting all pads, like the kit's own Q-Link macros. Known per-pad parameter IDs (instrumentIndex = pad): Filter Cutoff 514, Pan 517, Level 518, Decay 520, Send 1 522, Send 2 523. Missing: Tuning, Filter Reso, Filter Env, Attack, Release. First check that loading a different kit doesn't rename the track and break its name-based learns |
| Knob page B (8 more knobs via a second Hapax track on the same channel) | Built and tested, then shelved: it costs a Hapax track per plugin | A second Hapax definition per plugin, set to the same channel. The parked code isn't in this repo |

## License

MIT, see [LICENSE](LICENSE). Not affiliated with Akai/inMusic or Squarp. MPC and Hapax are their trademarks.
