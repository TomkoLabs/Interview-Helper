# 0.1.6 playback discovery repair

October 14, 2026. This focused patch changes discovery/parsing and error messages,
not audio configuration, drivers, ASR/model settings, credentials or cloud defaults.
No paid benchmark or further three-hour soak was run.

## Reproduction and correction

Before changing source, the exact supplied pactl 17 / PipeWire 1.4.2 output produced
`ValueError: Unrecognized pactl module topology` in 0.1.5. JSON contained 18 modules
without indices. The indexed short output contained those same 18 records across
57 physical lines, including multiline native SPA arguments. The old fallback
assumed every physical line was a module record and rejected the first continuation.

The fallback now consumes complete indexed records using the JSON module names and
literal arguments as boundaries. Newlines, tabs and comments inside those arguments
are preserved, not discarded. Indices still come exclusively from the indexed
short output. Duplicate/out-of-range/conflicting indices, changed names/arguments,
missing records and stray leading/trailing data fail visibly. A topology change
between JSON and short reads can therefore fail one discovery pass; the existing
two-second retry remains. It never invents an index from `properties.object.id`
or `object.serial`, including for native modules where values happen to agree.

Adjacent review found two relevant assumptions. Shell parsing is now limited to
the three supported Pulse forwarding module types; native PipeWire SPA arguments
are not shell syntax. Confirmed monitor associations are normalized to both source
name and Pulse source index, so numeric forwarding arguments also work when
`monitor_of_sink` is absent. Forwarding deduplication and independent downstream
mix handling remain intact; unknown/cyclic topology is not silently suppressed.

The supplied sources use reverse `monitor_source` names and `device.class=monitor`
for playback, with empty `monitor_source` and `device.class=sound` for physical
inputs. The existing sink-to-monitor names already identify both playback sources;
missing `monitor_of_sink` was not a second blocker for these exact outputs. The fix
retains authoritative sink/source relationships rather than admitting sources based
only on suffix, class or PipeWire object ID. An include-all pattern cannot admit
either physical input. Numeric sink monitor references are covered separately.

Diagnostics and the session pulse now identify the failed `pactl` list stage or
monitor-topology interpretation. Other capture errors retain a distinct capture
stage. Retry, timeout and continuous saving behavior is unchanged; raw server dumps
are not included in these messages.

## Validation and limits

- **116 tests passed**, including the existing PulseAudio, combine/loopback/cycle,
  include/exclude, session-saving and cloud regressions.
- Sanitized attachment fixture preserves all module names/arguments, 18 records /
  57 physical lines, Pulse indices, distinct PipeWire object IDs and monitor links.
  Host/user/cookie, hardware serials and device-identifying names were excluded.
- Exact original outputs also pass mocked-subprocess discovery: both analog/HDMI
  monitors found; both physical inputs excluded. Stream lists were absent from the
  attachment, so empty streams are an explicit test condition, not an observation.
- Malformed/truncated/mismatched records and duplicate/conflicting identities fail;
  arbitrary source naming does not bypass microphone exclusion. Native non-shell
  comments are tolerated while malformed supported forwarding arguments still fail.
- The existing **isolated real PulseAudio** test passed monitor discovery, 16 kHz
  mono float32 capture (peak 0.10388), null-sink hotplug, loopback dedup and disconnect.
  It used a private temporary server on development, with no desktop route changes.
- Ruff, project-owned format checks, package consistency, wheel/privacy and links
  checked. Vendored upstream formatting was left unchanged.

These checks do **not** establish actual Kraken/PipeWire audio capture. Installation
and CUDA/float16 warmup success are user-reported; no remote Kraken operation was
performed. After the [source-only update](KRAKEN_ACCEPTANCE.md#updating-to-018-and-migrating-sessions),
verify real playback activity, finalized transcript saves, microphone exclusion and
meeting behavior. The earlier 0.1.5 synthetic soak remains historical evidence.

Update-procedure correction: 0.1.7 contains this same audio fix and uses declared
build isolation for editable metadata refresh. The 0.1.6 archived checklist assumed
setuptools was already installed in the target venv; use the current checklist or
0.1.7 release instead. No runtime dependency or model change is involved.
