"""Keep console helpers invisible in the Windows GUI executable.

Patch the existing Popen initializer (rather than replace its class) so library
subclasses and previously imported references receive the same behavior.
Streams, process groups, priorities, cancellation and exit codes stay intact.
"""
import copy
import functools
import inspect
import os
import subprocess


def install():
    if os.name != "nt" or getattr(subprocess.Popen.__init__, "_editvideo_windowless", False):
        return
    original = subprocess.Popen.__init__
    signature = inspect.signature(original)

    @functools.wraps(original)
    def windowless_init(self, *args, **kwargs):
        bound = signature.bind(self, *args, **kwargs)
        flags = bound.arguments.get("creationflags", 0)
        # Preserve explicit requests for a separate console or detached process.
        if not flags & (subprocess.CREATE_NEW_CONSOLE | subprocess.DETACHED_PROCESS):
            bound.arguments["creationflags"] = flags | subprocess.CREATE_NO_WINDOW
            info = bound.arguments.get("startupinfo")
            info = copy.copy(info) if info is not None else subprocess.STARTUPINFO()
            info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            info.wShowWindow = subprocess.SW_HIDE
            bound.arguments["startupinfo"] = info
        original(*bound.args, **bound.kwargs)

    windowless_init._editvideo_windowless = True
    subprocess.Popen.__init__ = windowless_init


install()
