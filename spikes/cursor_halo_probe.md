# Cursor halo spike — probe transcript (2026-06-06)

Question: can portal cursor-mode *metadata* (4) deliver pointer coordinates
to a compositing element inside our `gst-launch-1.0` argv pipeline
(`record.py` `_gst_args`)?

Probes were non-interactive only (no portal sessions / live recordings were
started in this session — the empirical metadata-mode recording is left as a
manual verification step for Jack, commands below).

## 1. Does the portal offer metadata cursor mode?

```
$ gdbus call --session --dest org.freedesktop.portal.Desktop \
    --object-path /org/freedesktop/portal/desktop \
    --method org.freedesktop.DBus.Properties.Get \
    org.freedesktop.portal.ScreenCast AvailableCursorModes
(<uint32 7>,)
```

7 = 1|2|4 → hidden, embedded, **and metadata (4) are all offered**. Gate
condition (a) PASSES.

## 2. Does pipewiresrc expose any cursor-related property or meta API?

```
$ gst-inspect-1.0 pipewiresrc
Plugin Details:
  Name                     pipewire
  Filename                 /usr/lib64/gstreamer-1.0/libgstpipewire.so
  Version                  1.4.11
  ...
Element Properties:
  always-copy, autoconnect, automatic-eos, blocksize, client-name,
  client-properties, do-timestamp, fd, keepalive-time, max-buffers,
  min-buffers, name, num-buffers, parent, path, resend-last,
  stream-properties, target-object, typefind
```

No cursor-related property of any kind. Full output kept in shell history;
the property list above is exhaustive.

```
$ gst-inspect-1.0 pipewiresrc | grep -ic cursor
0
$ strings /usr/lib64/gstreamer-1.0/libgstpipewire.so | grep -ic cursor
0
```

Zero occurrences of "cursor" anywhere in the compiled plugin — pipewiresrc
1.4.11 does not parse `spa_meta_cursor` at all, let alone re-embed it or
expose it to downstream elements. Gate condition (b) FAILS.

## 3. Installed versions

```
$ rpm -q pipewire-gstreamer
pipewire-gstreamer-1.4.11-1.fc43.x86_64
$ gst-inspect-1.0 --version
gst-inspect-1.0 version 1.26.11
GStreamer 1.26.11
```

## Decision

**Branch B (document and park).** Condition (a) holds — the portal offers
cursor-mode metadata (AvailableCursorModes = 7). Condition (b) fails hard:
the gst-pipewire plugin binary contains no cursor handling whatsoever, so
with metadata mode the cursor would simply vanish from the frames and its
coordinates (delivered as PipeWire `spa_meta_cursor` per-buffer metadata)
would be dropped inside pipewiresrc with no way for any element in a
`gst-launch-1.0` pipeline string to read them. There is nowhere to composite
a halo without owning the pipeline in-process (appsink, or a pw_stream
consumer reading the buffer metadata directly) — that rewrite is the same
frame-source seam WS-D needs, so the halo rides along with WS-D.

## Manual verification for Jack (optional, confirms empirically)

1. In `wondershot/record.py` `_created`, temporarily change
   `"cursor_mode": GLib.Variant("u", 2)` to `GLib.Variant("u", 4)`.
2. `python -m wondershot`, record ~5 seconds while moving the mouse.
3. Expected: the cursor is ABSENT from the recorded frames (portal honored
   metadata mode) and nothing in the pipeline could have received its
   coordinates — confirming the park decision.
4. Revert the hardcode.
