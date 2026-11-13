"""Private process owner for native AEC; backend pipe EOF also releases the nodes.

This module uses only the standard library and never loads ASR/model resources.
PipeWire's pw-cli monitor mode does not exit on stdin EOF by itself.
"""

import os
import selectors
import signal
import subprocess
import sys


def own(arguments):
    stopping = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    child = subprocess.Popen(
        ["pw-cli", "-m", "load-module", "libpipewire-module-echo-cancel", arguments],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(sys.stdin, selectors.EVENT_READ)
            while not stopping and child.poll() is None:
                if selector.select(0.1) and not os.read(sys.stdin.fileno(), 1):
                    break
    finally:
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("AEC owner requires module arguments")
    raise SystemExit(own(sys.argv[1]))
