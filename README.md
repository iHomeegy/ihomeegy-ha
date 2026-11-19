# iHomeegy for Home Assistant

Control your iHomeegy units from Home Assistant, **locally**: no cloud, no internet needed.

Home Assistant joins your units the same way a family member does: the owner invites it from the iHomeegy app and
chooses which cards it may control. Every message is encrypted end to end (the same Noise protocol the iHomeegy app
uses), and the unit itself checks every command against the cards it was given.

## What you get

| Card in the app | In Home Assistant |
|---|---|
| ON/OFF lines, Energy Meter relay | Switch |
| Dimmers, DC LED dimmer, RGB strip | Light |
| Shutter | Cover (open / close / stop / position) |
| Fan | Fan (speeds) |
| Water / gas valve | Valve |
| Door lock | Lock |
| Gate pulse | Button |
| Thermostat | Climate |
| Siren | Siren |
| Inputs, RF hub sensors | Binary sensor (door, window, motion, smoke, gas, water leak, ...) |
| Temperature / humidity, Energy Meter readings | Sensor |
| Universal IR: TV remotes | Media player (power, volume, mute, channel up / down, channel number, inputs) |
| Universal IR: air conditioner remotes | Climate (off, modes, temperature, fan, swing) |

Universal IR remotes are made in the iHomeegy app; a remote added, changed or deleted there shows up in Home
Assistant within 5 minutes. A TV or an A/C never answers an infrared remote, so Home Assistant shows the last
setting sent (from Home Assistant, the app or a scene). Other remote kinds (fan, receiver, ...) are not shown yet.

Changes made in the iHomeegy app, by automations in the unit or by the wall switch show up in Home Assistant at once
(local push).

## Install (HACS)

1. HACS → ⋮ → **Custom repositories** → add `https://github.com/iHomeegy/ihomeegy-ha`, type **Integration**.
2. Find **iHomeegy** in HACS, **Download**, then restart Home Assistant.

## Add your units

1. In the iHomeegy app (owner or admin): **Members → Invite someone → With a QR code**, name it `Home Assistant`,
   choose the units and the cards it may control, then tap **Copy the code instead**.
2. In Home Assistant: **Settings → Devices & services → Add integration → iHomeegy**, paste the code.

The code works once and for 15 minutes. Home Assistant must be on the same network as the units.
Home Assistant shows up in the app's member list; removing it there takes its access away at once.
