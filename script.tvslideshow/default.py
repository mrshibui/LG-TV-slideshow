# -*- coding: utf-8 -*-
import json
import os
import random
import struct
import time

import xbmc
import xbmcaddon
import xbmcgui

try:
    from PIL import Image, ImageOps
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

ADDON = xbmcaddon.Addon()
ADDON_PATH = os.path.dirname(os.path.abspath(__file__))
BACKGROUND_IMAGE = os.path.join(ADDON_PATH, 'resources', 'white.png')

SLIDESHOW_ROOT = '/storage/Slideshow'
DEFAULT_PHOTOS_DIR = os.path.join(SLIDESHOW_ROOT, 'photos')
ROTATED_CACHE_DIR = os.path.join(SLIDESHOW_ROOT, '.rotated_cache')
STATE_FILE = os.path.join(SLIDESHOW_ROOT, '.slideshow_state.json')
# Bump this whenever the order-building logic changes, so a persisted state
# file from an older version of the addon gets rebuilt instead of reused.
STATE_VERSION = 2
IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.webp', '.bmp', '.gif')

POLL_SECONDS = 0.25
PAUSE_DEBOUNCE_SECONDS = 0.5

RUNNING_PROPERTY = 'tvslideshow.running'
HOME_WINDOW_ID = 10000



def ensure_paths():
    if not os.path.isdir(DEFAULT_PHOTOS_DIR):
        os.makedirs(DEFAULT_PHOTOS_DIR)


def get_photos_dir():
    """The folder to show photos from: the subfolder chosen in Settings (a
    button that opens Kodi's native folder browser), or DEFAULT_PHOTOS_DIR
    if none has been chosen yet or the chosen one no longer exists.
    """
    configured = ADDON.getSettingString('photosDir')
    if configured and os.path.isdir(configured):
        return configured
    if configured and configured != DEFAULT_PHOTOS_DIR:
        xbmc.log(
            '[script.tvslideshow] configured photos folder not found: %s (falling back to %s)'
            % (configured, DEFAULT_PHOTOS_DIR),
            xbmc.LOGWARNING
        )
    return DEFAULT_PHOTOS_DIR


def get_interval():
    return max(float(ADDON.getSettingInt('secondsPerPhoto')), 0.5)


def get_randomize():
    return ADDON.getSettingBool('randomize')


def get_background_color():
    return ADDON.getSettingString('backgroundColor') or 'ff000000'


def get_photo_fit():
    # Kodi ControlImage aspectRatio values: 2 = scale down (letterbox,
    # nothing cropped), 1 = scale up (fills the control, cropping excess).
    fit = ADDON.getSettingInt('photoFit')
    return fit if fit in (1, 2) else 2


def _read_exif_tiff(path):
    """Locate the EXIF APP1 segment in a JPEG and return (tiff_bytes, endian,
    ifd0_offset), or (None, None, None) if there isn't one / it's not a JPEG.
    """
    try:
        with open(path, 'rb') as f:
            data = f.read(131072)
    except OSError:
        return None, None, None

    if data[0:2] != b'\xff\xd8':
        return None, None, None

    i = 2
    length = len(data)
    try:
        while i + 4 <= length:
            if data[i] != 0xFF:
                break
            marker = data[i + 1]
            if marker in (0xD8, 0xD9):
                i += 2
                continue
            if 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            if marker == 0xDA:  # Start of Scan - no more metadata follows
                break
            seg_len = struct.unpack('>H', data[i + 2:i + 4])[0]
            if marker == 0xE1 and data[i + 4:i + 10] == b'Exif\x00\x00':
                tiff = data[i + 10:i + 2 + seg_len]
                if len(tiff) >= 8 and tiff[0:2] in (b'II', b'MM'):
                    endian = '<' if tiff[0:2] == b'II' else '>'
                    ifd0_offset = struct.unpack(endian + 'I', tiff[4:8])[0]
                    return tiff, endian, ifd0_offset
            i += 2 + seg_len
    except (struct.error, IndexError):
        pass
    return None, None, None


def _read_ifd(tiff, offset, endian):
    """Return {tag: (type, count, 4-byte value/offset field)} for one IFD."""
    entries = {}
    if offset + 2 > len(tiff):
        return entries
    try:
        num_entries = struct.unpack(endian + 'H', tiff[offset:offset + 2])[0]
        entries_start = offset + 2
        for entry_index in range(num_entries):
            entry_offset = entries_start + entry_index * 12
            if entry_offset + 12 > len(tiff):
                break
            tag, typ, count = struct.unpack(endian + 'HHI', tiff[entry_offset:entry_offset + 8])
            entries[tag] = (typ, count, tiff[entry_offset + 8:entry_offset + 12])
    except struct.error:
        pass
    return entries


def _ifd_short_value(entries, tag, endian):
    if tag not in entries:
        return None
    typ, count, value_bytes = entries[tag]
    try:
        return struct.unpack(endian + 'H', value_bytes[:2])[0]
    except struct.error:
        return None


def _ifd_offset_value(entries, tag, endian):
    if tag not in entries:
        return None
    typ, count, value_bytes = entries[tag]
    try:
        return struct.unpack(endian + 'I', value_bytes)[0]
    except struct.error:
        return None


def _ifd_ascii_value(tiff, entries, tag, endian):
    if tag not in entries:
        return None
    typ, count, value_bytes = entries[tag]
    if typ != 2:  # ASCII
        return None
    try:
        if count <= 4:
            raw = value_bytes[:count]
        else:
            offset = struct.unpack(endian + 'I', value_bytes)[0]
            raw = tiff[offset:offset + count]
    except struct.error:
        return None
    return raw.split(b'\x00', 1)[0].decode('ascii', errors='replace') or None


def read_exif_orientation(path):
    """Read the EXIF Orientation tag (1-8) from a JPEG file, defaulting to 1
    (normal) for non-JPEGs, files without EXIF, or any parse failure."""
    tiff, endian, ifd0_offset = _read_exif_tiff(path)
    if tiff is None:
        return 1
    ifd0 = _read_ifd(tiff, ifd0_offset, endian)
    return _ifd_short_value(ifd0, 0x0112, endian) or 1


def read_exif_datetime(path):
    """Read EXIF DateTimeOriginal ('YYYY:MM:DD HH:MM:SS', in the EXIF SubIFD)
    falling back to the top-level DateTime tag, or None if neither is present.
    """
    tiff, endian, ifd0_offset = _read_exif_tiff(path)
    if tiff is None:
        return None
    ifd0 = _read_ifd(tiff, ifd0_offset, endian)

    exif_ifd_offset = _ifd_offset_value(ifd0, 0x8769, endian)  # Exif IFD Pointer
    if exif_ifd_offset:
        exif_ifd = _read_ifd(tiff, exif_ifd_offset, endian)
        date_taken = _ifd_ascii_value(tiff, exif_ifd, 0x9003, endian)  # DateTimeOriginal
        if date_taken:
            return date_taken

    return _ifd_ascii_value(tiff, ifd0, 0x0132, endian)  # DateTime


def _photo_sort_key(path):
    # EXIF date strings ("YYYY:MM:DD HH:MM:SS") sort correctly as plain text.
    # Photos without a usable EXIF date fall back to file modification time,
    # formatted the same way so both kinds interleave in one chronological
    # order instead of being segregated into separate blocks.
    date_taken = read_exif_datetime(path)
    if not date_taken:
        try:
            date_taken = time.strftime('%Y:%m:%d %H:%M:%S', time.localtime(os.path.getmtime(path)))
        except OSError:
            date_taken = '9999:99:99 99:99:99'
    return (date_taken, os.path.basename(path))


def sort_by_date_taken(photos):
    return sorted(photos, key=_photo_sort_key)


def get_display_path(path):
    """Return the path to actually display for `path`: if it needs EXIF
    rotation/mirror correction and Pillow is available, returns a cached,
    corrected copy (generating/refreshing it as needed) without touching the
    original file at all. Falls back to the original path otherwise.
    """
    if not PIL_AVAILABLE or read_exif_orientation(path) == 1:
        return path

    cache_path = os.path.join(ROTATED_CACHE_DIR, os.path.basename(path))
    try:
        if (
            os.path.isfile(cache_path)
            and os.path.getmtime(cache_path) >= os.path.getmtime(path)
        ):
            return cache_path

        if not os.path.isdir(ROTATED_CACHE_DIR):
            os.makedirs(ROTATED_CACHE_DIR)

        image = ImageOps.exif_transpose(Image.open(path))
        image.save(cache_path, quality=90)
        xbmc.log('[script.tvslideshow] cached orientation-corrected copy of %s' % path, xbmc.LOGINFO)
        return cache_path
    except Exception as exc:
        xbmc.log(
            '[script.tvslideshow] failed to correct orientation for %s: %s' % (path, exc),
            xbmc.LOGWARNING
        )
        return path


def _is_readable_image_file(path):
    try:
        return os.path.getsize(path) > 0
    except OSError:
        return False


def load_photos(photos_dir):
    try:
        names = sorted(
            name for name in os.listdir(photos_dir)
            if name.lower().endswith(IMAGE_EXTENSIONS)
        )
        paths = [os.path.join(photos_dir, name) for name in names]
    except Exception:
        return []

    photos = [p for p in paths if _is_readable_image_file(p)]
    skipped = len(paths) - len(photos)
    if skipped:
        xbmc.log(
            '[script.tvslideshow] skipping %d empty/unreadable file(s) in %s' % (skipped, photos_dir),
            xbmc.LOGWARNING
        )
    return photos


def _load_state():
    try:
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    except Exception:
        return None


def _save_state(photos, position, randomize):
    state = {
        'stateVersion': STATE_VERSION,
        'order': [os.path.basename(p) for p in photos],
        'position': position,
        'randomize': randomize,
    }
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump(state, f)
    except Exception:
        pass  # non-fatal - worst case we lose the resume position


def build_photo_order(photos, randomize):
    """Restore a previous run's order/position if the photo set is unchanged
    (so a restart - e.g. by the auto-start service - resumes where it left
    off instead of reshuffling and repeating early photos), otherwise start
    a fresh (optionally shuffled/date-sorted) order at position 0.
    """
    names_by_basename = {os.path.basename(p): p for p in photos}
    state = _load_state()

    if (
        state
        and state.get('stateVersion') == STATE_VERSION
        and state.get('randomize') == randomize
        and sorted(state.get('order', [])) == sorted(names_by_basename)
    ):
        order = [names_by_basename[name] for name in state['order']]
        position = state.get('position', 0) % len(order)
        return order, position

    if randomize:
        order = list(photos)
        random.shuffle(order)
    else:
        order = sort_by_date_taken(photos)
    return order, 0


class SlideshowWindow(xbmcgui.WindowDialog):

    def __init__(self, photos, position, randomize, background_color, photo_fit):
        super(SlideshowWindow, self).__init__()
        self.photos = photos
        self.index = 0
        self.randomize = randomize
        self.photo_fit = photo_fit
        self.closed = False
        self.paused = False
        self._last_pause_toggle = 0.0
        self.image = None

        # Reverted: xbmcgui.getScreenWidth()/getScreenHeight() (the true
        # output resolution) made the margin issue worse, not better - one
        # side vanished entirely - which means control coordinates here
        # aren't in that space. Window.getWidth()/getHeight() is what the
        # background control has been using successfully (it always covered
        # the full visible screen with no gaps reported), so it's what
        # actually matches the coordinate space controls are placed in here.
        self._screen_width = self.getWidth()
        self._screen_height = self.getHeight()

        # Opaque full-screen background so the Kodi interface behind this
        # window never shows through the letterboxed area around a photo.
        # A tiny bundled white texture, stretched and tinted via colorDiffuse,
        # is the standard Kodi trick for a solid-color fill.
        self.background = xbmcgui.ControlImage(
            0, 0, self._screen_width, self._screen_height, BACKGROUND_IMAGE, colorDiffuse=background_color
        )
        self.addControl(self.background)

        if self.photos:
            self._show(position)

    def onAction(self, action):
        action_id = action.getId()
        if action_id in (xbmcgui.ACTION_PREVIOUS_MENU, xbmcgui.ACTION_NAV_BACK):
            self.closed = True
            self.close()
        elif action_id == xbmcgui.ACTION_MOVE_LEFT:
            self.show_previous()
        elif action_id == xbmcgui.ACTION_MOVE_RIGHT:
            self.show_next()
        elif action_id == xbmcgui.ACTION_PLAYER_PLAY:
            # Dedicated Play button: always resume.
            self.set_paused(False)
        elif action_id == xbmcgui.ACTION_PAUSE:
            # Pause button: toggles, so it also works as a combined
            # Play/Pause button on remotes that only have one.
            self.set_paused(not self.paused)

    def set_paused(self, paused):
        # A single remote press can deliver several onAction calls in quick
        # succession (button repeat); debounce so that doesn't flip the
        # state back and forth and spam the notification.
        now = time.time()
        if now - self._last_pause_toggle < PAUSE_DEBOUNCE_SECONDS:
            return
        self._last_pause_toggle = now

        if paused == self.paused:
            return
        self.paused = paused
        xbmcgui.Dialog().notification(
            'TV Slideshow', 'Paused' if paused else 'Resumed',
            xbmcgui.NOTIFICATION_INFO, 1500
        )

    def show_next(self):
        if not self.photos:
            return
        previous_path = self.photos[self.index]
        next_index = (self.index + 1) % len(self.photos)
        if next_index == 0 and self.randomize and len(self.photos) > 1:
            # Starting a new lap: reshuffle so it doesn't repeat the exact
            # same order every time, but avoid the last photo of this lap
            # landing first in the new one (would look like a repeat).
            random.shuffle(self.photos)
            if self.photos[0] == previous_path:
                swap_with = random.randint(1, len(self.photos) - 1)
                self.photos[0], self.photos[swap_with] = self.photos[swap_with], self.photos[0]
        self._show(next_index)

    def show_previous(self):
        if not self.photos:
            return
        self._show(self.index - 1)

    def _show(self, index):
        self.index = index % len(self.photos)
        path = self.photos[self.index]
        # So a black screen can be tracked back to the exact file that was
        # showing at the time, in kodi.log, if the image failed to decode.
        xbmc.log('[script.tvslideshow] showing %s' % path, xbmc.LOGINFO)

        display_path = get_display_path(path)

        if self.image is not None:
            self.removeControl(self.image)
        # aspectRatio: 2 = scale down (letterbox, nothing cropped),
        # 1 = scale up (fills the control, cropping excess) - Kodi's own
        # fit/centering handling. The earlier asymmetric-margin issue turned
        # out to be a device-level GUI calibration offset, not a bug in this
        # (or any) fit/centering approach, so there's no need for the more
        # complex manual-compositing workaround that was tried in between.
        image = xbmcgui.ControlImage(
            0, 0, self._screen_width, self._screen_height, display_path, aspectRatio=self.photo_fit
        )
        self.addControl(image)
        self.image = image


def run():
    ensure_paths()
    # LOGWARNING rather than LOGINFO so this always makes it into kodi.log
    # regardless of whether debug logging is enabled.
    xbmc.log('[script.tvslideshow] PIL available: %s' % PIL_AVAILABLE, xbmc.LOGWARNING)

    photos_dir = get_photos_dir()
    xbmc.log('[script.tvslideshow] using photos folder: %s' % photos_dir, xbmc.LOGWARNING)

    randomize = get_randomize()
    photos, position = build_photo_order(load_photos(photos_dir), randomize)

    interval = get_interval()
    background_color = get_background_color()
    photo_fit = get_photo_fit()

    if not photos:
        xbmcgui.Dialog().notification(
            'TV Slideshow', 'No photos found in ' + photos_dir,
            xbmcgui.NOTIFICATION_INFO, 5000
        )

    home_window = xbmcgui.Window(HOME_WINDOW_ID)
    home_window.setProperty(RUNNING_PROPERTY, '1')

    # Prevent Kodi's own screensaver/display-off from kicking in while the
    # slideshow is the thing actually on screen.
    xbmc.executebuiltin('InhibitScreensaver(true)')

    window = SlideshowWindow(photos, position, randomize, background_color, photo_fit)
    window.show()

    if photos:
        _save_state(window.photos, window.index, randomize)

    try:
        monitor = xbmc.Monitor()
        last_index = window.index
        elapsed = 0.0

        # Poll in short ticks (rather than sleeping for the whole interval at
        # once) so pausing, resuming, navigating and exiting all stay
        # responsive instead of waiting for the current interval to finish.
        while photos and not monitor.abortRequested() and not window.closed:
            if monitor.waitForAbort(POLL_SECONDS):
                break
            if window.closed:
                break

            # Belt-and-braces: also actively reset the idle/screensaver timer
            # each tick, in case InhibitScreensaver alone isn't enough.
            xbmc.executebuiltin('ResetScreenSaver()')

            if window.index != last_index:
                # Manual navigation happened; restart the countdown and
                # remember the new position (and possibly reshuffled order).
                last_index = window.index
                elapsed = 0.0
                _save_state(window.photos, window.index, randomize)
                continue

            if window.paused:
                elapsed = 0.0
                continue

            elapsed += POLL_SECONDS
            if elapsed >= interval:
                window.show_next()
                last_index = window.index
                elapsed = 0.0
                _save_state(window.photos, window.index, randomize)
    finally:
        window.close()
        del window
        xbmc.executebuiltin('InhibitScreensaver(false)')
        home_window.clearProperty(RUNNING_PROPERTY)


if __name__ == '__main__':
    run()
