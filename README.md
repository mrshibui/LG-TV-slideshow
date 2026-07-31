# TV Slideshow (Kodi / CoreELEC addons)

A minimal full-screen photo slideshow for the Ugoos AM6B running CoreELEC, built as two Kodi addons. Photos live directly on the box's storage — no network/NAS dependency — and everything else is configured through Kodi's own native addon Settings screens (no file editing needed).

- **`script.tvslideshow`** — the slideshow itself. Launch it manually, or let the service below start it for you.
- **`service.tvslideshow.autostart`** — an optional background watcher that auto-launches the slideshow after a configurable period of inactivity, screensaver-style, without the limitations of a real Kodi screensaver (see below).

## How it works

- Put your photos in **`/storage/Slideshow/photos/`** on the box (supports `.jpg`, `.jpeg`, `.png`, `.webp`, `.bmp`, `.gif`) — either directly, or organized into subfolders (e.g. one per trip/album: `photos/Japan/`, `photos/Oostenrijk/`, ...) and pick which one to show via the *Photos folder* setting. The base `photos/` folder is created automatically the first time the slideshow runs if it doesn't already exist.
- Configure everything via each addon's **Settings** screen (the gear icon shown on its info panel in `Add-ons > My add-ons`):
  - **TV Slideshow** settings:
    - *Photos folder* — a Browse button (Kodi's native folder picker) for which folder to actually show photos from. Defaults to `/storage/Slideshow/photos` itself; click Browse and navigate into a subfolder (e.g. `photos/Japan`) to show only that album. Only the selected folder's photos are used — not its subfolders, and not the other albums. If the selected folder is ever missing (e.g. renamed/deleted), it automatically falls back to the default `photos/` folder rather than showing nothing.
    - *Seconds per photo* — how long each photo stays on screen.
    - *Random order* — shuffle the photo order (default on). Every photo is shown once before any repeat, including across restarts (e.g. by the auto-start service) — progress through the current shuffled order is remembered in `/storage/Slideshow/.slideshow_state.json` and only reshuffled once every photo has been shown, or when photos are added/removed. When turned **off**, photos are shown in chronological order by when they were actually taken (read from each photo's EXIF date, falling back to file modification time for photos without one) rather than by filename — so photos from a different camera/export batch with a differently-numbered filename still fall in the right place.
    - *Background color* — opens Kodi's color picker; fills the screen behind/around each photo (default opaque black). Keep it fully opaque — a translucent color lets the Kodi interface show through again.
    - *Photo fit* — **Show complete photo (black bars)** (default) scales each photo to fit the screen without cropping, letterboxed against the background color; **Fill screen (crop photo)** scales it up to cover the whole screen instead, cropping whichever edges don't fit.
  - **TV Slideshow Auto-start** settings:
    - *Idle minutes before auto-start* — minutes of no remote input before the slideshow launches itself (see below). Set to `0` to disable auto-start.
- Each photo is scaled according to the *Photo fit* setting above (Kodi's own aspect-fit handling), and always fills whatever resolution Kodi's GUI is currently running at (1080p, 4K, etc.), since the display area is read live from Kodi rather than hardcoded.
- Remote control: **Left** goes to the previous photo, **Right** advances — either resets the auto-advance interval. **Pause** pauses the auto-advance (toggles, so it also works as a combined Play/Pause button); **Play** always resumes. These are Kodi's standard D-pad/media-transport actions, so any remote already paired with Kodi works with no extra setup. **Back** exits. A brief on-screen notification confirms Paused/Resumed.
- While the slideshow is on screen, Kodi's own screensaver/display-off is held off, so it won't go black on its own.
- Relaunching the addon re-scans the photos folder and re-reads its settings, so adding/removing photos or changing settings doesn't require reinstalling anything — just relaunch (or wait for auto-start). Adding/removing photos resets the shuffle progress (a fresh order starting from the beginning); otherwise a restart resumes exactly where the previous run left off.

**Note on 4K:** to actually see photos rendered at 4K, Kodi's GUI resolution itself needs to be set to 2160p (`Settings > System > Display > Resolution`) — this is a device setting, independent of the addon, since Kodi's picture/GUI layer renders at whatever the GUI resolution is (unlike video playback, which can switch resolution automatically per file).

## Why a background service instead of a real Kodi screensaver

Kodi has a native screensaver addon type, but it wasn't used here for two reasons: any remote press dismisses an active Kodi screensaver outright (back to the home screen) rather than passing the key through, which would break Left/Right photo navigation; and Python-based screensaver addons have a known Kodi core reliability issue. Instead, `service.tvslideshow.autostart` runs quietly in the background, checks Kodi's idle time against its own "Idle minutes before auto-start" setting every few seconds, and — as long as nothing is currently playing and the slideshow isn't already running — just launches `script.tvslideshow` the normal way. Functionally it behaves like a screensaver, but Left/Right/Back keep working exactly as when launched manually.

It also tracks the moment playback actually stops (rather than trusting Kodi's raw idle-time counter alone, which keeps climbing throughout a long movie with no button presses) — so finishing a movie gives you the full idle-minutes window at Kodi's normal menu before the slideshow takes over, instead of it appearing immediately.

Since it's a **service** addon, Kodi gives it no "Run" button in the Add-ons UI — that's expected, not a bug. Kodi starts/stops it automatically as soon as it's enabled/disabled, and again on every future Kodi restart, with no manual trigger needed.

### Verifying the service is actually running

It logs a line on startup and whenever it triggers the slideshow. To check:
```bash
ssh root@<box-ip> "tail -f /storage/.kodi/temp/kodi.log"
```
Look for `[service.tvslideshow.autostart] service started` right after enabling it or rebooting, and `[service.tvslideshow.autostart] idle threshold reached, launching slideshow` once the idle timer trips. Simplest end-to-end check: leave the box alone (no remote input, nothing playing) for the configured number of idle minutes and confirm the slideshow appears on its own.

## Installing on the CoreELEC box

1. Enable SSH: on the TV, `Settings > CoreELEC > Services > SSH`, turn it on. Default login is `root` / `coreelec` (change the password if you haven't already).
2. Copy both addon folders to the box:
   ```bash
   scp -r script.tvslideshow service.tvslideshow.autostart root@<box-ip>:/storage/.kodi/addons/
   ```
3. Restart Kodi so it picks up the new addons (either reboot the box, or from an SSH session: `systemctl restart kodi`).
4. If they're not already active, enable both: `Settings > Add-ons > My add-ons`, find **TV Slideshow** under Program add-ons and **TV Slideshow Auto-start** under Services, and enable each.
   - Only installed `script.tvslideshow` and want to launch it manually (no auto-start)? Skip installing/enabling the service addon entirely.
5. Configure each addon from its own Settings screen (the gear icon in its info panel) — see "How it works" above for what each setting does.
6. Launch the slideshow manually any time from `Add-ons > Program add-ons > TV Slideshow`, or just leave the box idle for the configured number of minutes and let the service start it for you.

## Adding photos

```bash
scp myphoto1.jpg myphoto2.jpg root@<box-ip>:/storage/Slideshow/photos/Japan/
```
(adjust the path to whichever folder/album you're adding to, or straight into `photos/` if you're not using subfolders). No reinstall or settings change needed — just relaunch the slideshow (or wait for the auto-start service) to pick up new/removed photos in the currently-selected folder.

**Portrait photos:** Kodi's image control displays a photo's raw stored pixels and, unlike macOS (Finder/Preview), does not apply the EXIF orientation tag on its own — cameras/phones commonly store a portrait shot as rotated landscape pixels plus a tag saying how to rotate it for display. The addon corrects this using Pillow (PIL) if it's available in Kodi's own Python environment: it generates a correctly-oriented copy of any photo that needs it (checking the EXIF tag itself, so this only applies to the photos that actually need it), cached under `/storage/Slideshow/.rotated_cache/`, and displays that instead — your original files are never touched.

If Pillow isn't available in Kodi's Python (check `kodi.log` for `PIL available: False` right after launching the slideshow), portrait photos fall back to showing full-size but sideways rather than failing.

**A note on an asymmetric black bar on one side:** if you ever see this, it's very likely a Kodi GUI calibration issue on the device itself, not something fixable in the addon - check `Settings > System > Display > Calibrate` and make sure the (default, unadjusted) calibration rectangle actually lines up with your TV's true visible edges. This can go unnoticed for a long time since normal Kodi menus have their own built-in margins that mask a small miscalibration - it only shows up on genuinely edge-to-edge content like this slideshow's full-screen photos.

## Optional: launching with a remote button

You can also bind a specific remote button to launch the slideshow on demand, in addition to (or instead of) the auto-start service, via a Kodi keymap entry that runs:
```
RunScript(script.tvslideshow)
```
See the [Kodi keymap documentation](https://kodi.wiki/view/Keymap) for how to map a specific key/button to that action.
