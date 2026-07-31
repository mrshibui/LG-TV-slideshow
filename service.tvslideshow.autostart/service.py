# -*- coding: utf-8 -*-
import time

import xbmc
import xbmcaddon
import xbmcgui

ADDON = xbmcaddon.Addon()

POLL_SECONDS = 5

RUNNING_PROPERTY = 'tvslideshow.running'
HOME_WINDOW_ID = 10000


def get_idle_minutes():
    return ADDON.getSettingInt('idleMinutesBeforeStart')


def is_slideshow_running():
    return xbmcgui.Window(HOME_WINDOW_ID).getProperty(RUNNING_PROPERTY) == '1'


class PlaybackTracker(xbmc.Player):
    """Tracks when playback last ended.

    Kodi's own xbmc.getGlobalIdleTime() only measures time since the last
    remote input - it keeps climbing throughout a long movie with no button
    presses, so right after playback ends it can already be hours old. Used
    on its own, that would trigger the slideshow immediately instead of
    letting Kodi's normal post-playback menu show. Requiring idle time to
    also be measured from the moment playback actually stopped fixes that.
    """

    def __init__(self):
        super(PlaybackTracker, self).__init__()
        self.playback_ended_at = time.time()

    def onPlayBackEnded(self):
        self.playback_ended_at = time.time()

    def onPlayBackStopped(self):
        self.playback_ended_at = time.time()

    def onPlayBackError(self):
        self.playback_ended_at = time.time()


def run():
    xbmc.log('[service.tvslideshow.autostart] service started', xbmc.LOGINFO)

    monitor = xbmc.Monitor()
    player = PlaybackTracker()

    while not monitor.abortRequested():
        if monitor.waitForAbort(POLL_SECONDS):
            break

        idle_minutes = get_idle_minutes()
        if idle_minutes <= 0:
            continue  # 0 disables auto-start

        if player.isPlaying():
            continue

        if is_slideshow_running():
            continue

        seconds_since_playback = time.time() - player.playback_ended_at
        idle_seconds = min(xbmc.getGlobalIdleTime(), seconds_since_playback)

        if idle_seconds >= idle_minutes * 60:
            xbmc.log('[service.tvslideshow.autostart] idle threshold reached, launching slideshow', xbmc.LOGINFO)
            xbmc.executebuiltin('RunScript(script.tvslideshow)')

    xbmc.log('[service.tvslideshow.autostart] service stopped', xbmc.LOGINFO)


if __name__ == '__main__':
    run()
