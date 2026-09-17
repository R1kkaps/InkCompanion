# epdiy.cn interoperability notes

## 2026-09-14 connection and display update

The desktop initializes the existing driver after a user connection action. The standalone
ble_connection.py remains read-only. Display validation status is tracked in VALIDATION.md.

The installed Bleak 3.0.2 WinRT client gets an integer address from BLEDevice and does not
automatically copy its ADV address type. The connector reads `device.details.adv` (or scan
response) `bluetooth_address_type` and explicitly passes `winrt.address_type` as random/public.
This is a version-specific adapter and covered by tests; absence of metadata does not
trigger guessing from MAC bits. See https://bleak.readthedocs.io/en/latest/backends/windows.html.

Observed services: FE59 (3 characteristics), EPD service 62750001… (2 characteristics).
EPD 62750002…: notify, write-without-response, write. EPD 62750003…: read.
The earlier read-only validation did not write or subscribe; display mode subscribes only to the EPD characteristic. No DFU or pairing command is implemented.

Observed 2026-09-14 from the public browser client at
https://epdiy.cn/assets/index-DJ17L3Pz.js (download retained locally for research only).
Application code is an independent implementation. The website bundle is not bundled with the executable.

## BLE

Service: `62750001-d828-918d-fb46-b6c11c675aec`.
Read/write/notify characteristic: `62750002-d828-918d-fb46-b6c11c675aec`.
Firmware version characteristic: `62750003-d828-918d-fb46-b6c11c675aec`.
Target supplied by owner: `NRF_EPD_71E9`, panel `ZKC42VM`, 4.2 inch.
400×300 is the website's 4.2 inch preset; panel-specific validation remains required.

1. Subscribe to notifications, send `01` without a driver argument, collect configuration.
   First binary response has current driver at byte 7. Chunked config has ASCII
   `chunk=N len=N` followed by the announced number of binary bytes.
2. Notifications include `mtu=N rle=0/1`, `slots=N ...`, `t=N bat=N`, `sid=...`, `err=busy`.
   In the site's image path, `mtu` is used as the entire characteristic-write length,
   not ATT MTU; use min(reported length, OS write limit, 244), two header bytes deducted.
3. Website POSTs form `hash=<sid>` to `https://epdiy.cn/ecc/check`; accepts `OK`.
   Desktop follows this check, does not log SID, refuses image writes on missing/failed check.
   No firmware flashing, pin configuration, driver selection or reset command is implemented.
4. Before a frame: send `01`, delay 200 ms. Pixels are row-major, leftmost bit is MSB,
   white=1, black=0, padding at the end of each row is zero. 400×300 = 15,000 bytes.
5. Frame writes start with `30`, then a flags byte, then image bytes.
   Legacy BW flags: first `0F`, following `FF`. Legacy red: first `00`, following `F0`.
   New protocol (only when `rle=1`): bit0 red plane, bit1 start plane, bit2 compressed.
   New uncompressed writes still use the new flags. Do not use legacy flags after negotiating RLE.
6. RLE: high bit set = repeat following byte `(tag & 127)+3` times (3–130);
   high bit clear = copy following `tag+1` bytes (1–128). Tokens must not span write packets.
   Use compressed packets only if their aggregate payload is smaller.
7. Website alternates 10 writes without response then 1 with response. Desktop follows this
   with 6 ms pacing and additionally requests a response for the last image block.
8. Submit `05` for refresh. Website also has `05 A5`, but its physical effect has not been
   established; desktop does not label/use it as partial or fast refresh.

Supported driver IDs: 01, 04, 17 (4.2 inch BW); 02, 03, 16 (4.2 inch BWR).
For BWR, the BW plane and an explicit red plane are both sent. The website encoder and decoder show that the red plane is active-low: bit 0 means red, bit 1 means non-red. Therefore an all-0xFF red plane clears old red pixels. With dithering enabled, pixels are quantized against the website's black/white/red RGB palette and color-channel errors are diffused with the selected website kernel. With dithering disabled, the website's luminance threshold 140 and red rule R > 160, R > G, R > B are used (the desktop keeps those thresholds adjustable). Four-color and other drivers are gated until explicitly adapted.
Slot notification: slots=<count> <used bitmask> <current zero-based slot>.
For a new image, issue 31 00 <slot> BEFORE INIT, then transfer both planes and REFRESH.
Select an empty slot, or one successfully written during this connection only; preserve all
pre-existing slots. Cached images use 31 01 <slot> to request display without retransmission.
No FREE_SLOT or built-in slideshow command is sent. Cache ownership is session-local;
cross-session slot reclamation is not implemented.

## Refresh limits and error handling

The public client has no verified refresh-complete acknowledgement. Successful BLE writes
are not proof of a correct physical display. Desktop uses a configurable 15 s default wait,
one active transfer, content deduplication and at most one pending/latest rendered frame.
On write error, busy reply, cancellation or disconnect, stop automatic sending. Never
submit refresh for a partly transferred frame. Start a later retry with INIT and a new frame.
No speculative partial-refresh command or custom waveform is sent.

## Music

Read Windows GlobalSystemMediaTransportControlsSessionManager, MediaProperties and Thumbnail.
Sources: [Microsoft API](https://learn.microsoft.com/en-us/uwp/api/windows.media.control.globalsystemmediatransportcontrolssessionmediaproperties),
[Bleak client](https://bleak.readthedocs.io/en/latest/api/client.html).
Poll every 2 s, hash actual thumbnail bytes as well as title/artist, render locally.
NetEase must expose an SMTC session; no account login or cloud-music API scraping is required.
No microphone/system audio recording is used. A missing thumbnail is explicitly identified.
