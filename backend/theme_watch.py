"""Linux file events: react before Omarchy's slower application hooks finish."""
import asyncio
import ctypes
import os
import struct


class ThemeWatch:
    def __init__(self, directory, callback):
        self.loop = asyncio.get_running_loop()
        self.callback = callback
        self.timer = None
        libc = ctypes.CDLL(None, use_errno=True)
        self.fd = libc.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
        if self.fd < 0:
            raise OSError(ctypes.get_errno(), 'Could not watch theme changes')
        # Close-write + moved-to cover theme.name and the replaced theme folder.
        if libc.inotify_add_watch(self.fd, os.fsencode(directory), 0x8 | 0x80) < 0:
            os.close(self.fd)
            raise OSError(ctypes.get_errno(), 'Could not watch theme folder')
        self.loop.add_reader(self.fd, self.read)

    def read(self):
        try:
            data = os.read(self.fd, 65536)
        except BlockingIOError:
            return
        offset, relevant = 0, False
        while offset + 16 <= len(data):
            _, _, _, length = struct.unpack_from('iIII', data, offset)
            name = data[offset + 16:offset + 16 + length].split(b'\0')[0]
            relevant |= name in (b'theme', b'theme.name')
            offset += 16 + length
        if relevant:
            if self.timer:
                self.timer.cancel()
            self.timer = self.loop.call_later(0.02, self.callback)

    def close(self):
        if self.timer:
            self.timer.cancel()
        self.loop.remove_reader(self.fd)
        os.close(self.fd)
