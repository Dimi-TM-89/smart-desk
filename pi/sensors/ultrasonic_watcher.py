"""
ultrasonic_watcher.py – Measures the HC-SR04 continuously in a thread of its
own (multithreading, course lesson 5).

Why a thread?
    One distance takes about 0.2–0.3 s: several echoes with 60 ms rest in
    between (the HC-SR04 needs that). In the main loop of desk_controller.py
    that would block the buttons each time, and measuring only once per second
    could miss a hand or figure that passes the entrance quickly.
    This thread measures non-stop (about 5x per second) and remembers:
        distance   the newest distance in cm (None = no echo)
        last_seen  time.monotonic() of the last time someone was at the entrance

"Someone" = CONFIRM readings in a row clearly shorter than the baseline (the
empty scene measured at startup), so one bad echo is not a visitor.

The main thread only reads these two values; they are written by this thread
under a lock.
"""

import threading
import time

SAMPLES = 3            # echoes per distance (median), ~0.2 s
CONFIRM = 2            # readings in a row below the baseline before it counts


class UltrasonicWatcher:
    """Background measurement of an Ultrasonic sensor that has been calibrated."""

    def __init__(self, ultrasonic, drop_cm):
        """Start the thread. drop_cm: how much shorter than the baseline counts as someone."""
        self.ultrasonic = ultrasonic
        self.drop_cm = drop_cm
        self.error = None                      # exception that stopped the thread, if any
        self._distance = None
        self._last_seen = None
        self._lock = threading.Lock()          # protects _distance and _last_seen
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="ultrasonic", daemon=True)
        self._thread.start()

    # --- read from the main thread -----------------------------------------
    @property
    def distance(self):
        """Newest distance in cm, or None (no echo / not measured yet)."""
        with self._lock:
            return self._distance

    @property
    def last_seen(self):
        """time.monotonic() of the last detection at the entrance, or None."""
        with self._lock:
            return self._last_seen

    @property
    def alive(self):
        """False if the thread has stopped (after stop() or an error)."""
        return self._thread.is_alive()

    def stop(self, timeout=2):
        """End the thread and wait for it."""
        self._stop.set()
        self._thread.join(timeout)

    # --- the measuring thread ----------------------------------------------
    def _run(self):
        """Thread body: measure, update the shared values, repeat until stop()."""
        baseline = self.ultrasonic.baseline_cm
        hits = 0
        try:
            while not self._stop.is_set():
                d = self.ultrasonic.distance_cm(SAMPLES)
                close = baseline is not None and d is not None and d < baseline - self.drop_cm
                hits = hits + 1 if close else 0
                with self._lock:
                    self._distance = d
                    if hits >= CONFIRM:
                        self._last_seen = time.monotonic()
        except Exception as exc:  # noqa: BLE001 – reported by the main thread
            self.error = exc
