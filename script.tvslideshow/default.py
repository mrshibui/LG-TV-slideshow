# -*- coding: utf-8 -*-
import os
import random
import time

import xbmc
import xbmcaddon
import xbmcgui

ADDON = xbmcaddon.Addon()
ADDON_PATH = os.path.dirname(os.path.abspath(__file__))
BACKGROUND_IMAGE = os.path.join(ADDON_PATH, 'resources', 'white.png')

SLIDESHOW_ROOT = '/storage/Slideshow'
PHOTOS_DIR = os.path.join(SLIDESHOW_ROOT, 'photos')
IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.webp', '.bmp', '.gif')

POLL_SECONDS = 0.25
PAUSE_DEBOUNCE_SECONDS = 0.5

RUNNING_PROPERTY = 'tvslideshow.running'
HOME_WINDOW_ID = 10000


def ensure_paths():
    if not os.path.isdir(PHOTOS_DIR):
        os.makedirs(PHOTOS_DIR)


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


def _is_readable_image_file(path):
    try:
        return os.path.getsize(path) > 0
    except OSError:
        return False


def load_photos():
    try:
        names = sorted(
            name for name in os.listdir(PHOTOS_DIR)
            if name.lower().endswith(IMAGE_EXTENSIONS)
        )
        paths = [os.path.join(PHOTOS_DIR, name) for name in names]
    except Exception:
        return []

    photos = [p for p in paths if _is_readable_image_file(p)]
    skipped = len(paths) - len(photos)
    if skipped:
        xbmc.log(
            '[script.tvslideshow] skipping %d empty/unreadable file(s) in %s' % (skipped, PHOTOS_DIR),
            xbmc.LOGWARNING
        )
    return photos


class SlideshowWindow(xbmcgui.WindowDialog):

    def __init__(self, photos, background_color, photo_fit):
        super(SlideshowWindow, self).__init__()
        self.photos = photos
        self.index = 0
        self.closed = False
        self.paused = False
        self._last_pause_toggle = 0.0

        width = self.getWidth()
        height = self.getHeight()

        # Opaque full-screen background so the Kodi interface behind this
        # window never shows through the letterboxed area around a photo.
        # A tiny bundled white texture, stretched and tinted via colorDiffuse,
        # is the standard Kodi trick for a solid-color fill.
        self.background = xbmcgui.ControlImage(
            0, 0, width, height, BACKGROUND_IMAGE, colorDiffuse=background_color
        )
        self.addControl(self.background)

        # getWidth()/getHeight() report this window's actual size in whatever
        # resolution Kodi's GUI is currently running at, so the image control
        # always spans the full screen regardless of output resolution.
        # photo_fit is Kodi's own aspectRatio value: 2 ("scale down") fits the
        # whole photo without cropping (letterboxed), 1 ("scale up") fills the
        # screen completely, cropping whichever axis doesn't match.
        self.image = xbmcgui.ControlImage(0, 0, width, height, '', aspectRatio=photo_fit)
        self.addControl(self.image)
        if self.photos:
            self._show(0)

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
        self._show(self.index + 1)

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
        self.image.setImage(path)


def run():
    ensure_paths()

    photos = load_photos()
    if get_randomize():
        random.shuffle(photos)

    interval = get_interval()
    background_color = get_background_color()
    photo_fit = get_photo_fit()

    if not photos:
        xbmcgui.Dialog().notification(
            'TV Slideshow', 'No photos found in ' + PHOTOS_DIR,
            xbmcgui.NOTIFICATION_INFO, 5000
        )

    home_window = xbmcgui.Window(HOME_WINDOW_ID)
    home_window.setProperty(RUNNING_PROPERTY, '1')

    # Prevent Kodi's own screensaver/display-off from kicking in while the
    # slideshow is the thing actually on screen.
    xbmc.executebuiltin('InhibitScreensaver(true)')

    window = SlideshowWindow(photos, background_color, photo_fit)
    window.show()

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
                # Manual navigation happened; restart the countdown.
                last_index = window.index
                elapsed = 0.0
                continue

            if window.paused:
                elapsed = 0.0
                continue

            elapsed += POLL_SECONDS
            if elapsed >= interval:
                window.show_next()
                last_index = window.index
                elapsed = 0.0
    finally:
        window.close()
        del window
        xbmc.executebuiltin('InhibitScreensaver(false)')
        home_window.clearProperty(RUNNING_PROPERTY)


if __name__ == '__main__':
    run()
