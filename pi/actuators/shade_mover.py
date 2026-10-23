"""
shade_mover.py – Moves the sunshade in a thread of its own (multithreading,
course lesson 5).

Why a thread?
    Shade.move_to() blocks: a full open/close is 2048 half steps of 1.2 ms,
    about 3 seconds. In the main loop of desk_controller.py that would freeze
    the sensors, both buttons, the lamp and (later) the OLED during every
    movement. With this class the main loop only says WHERE the shade has to
    go; a separate thread does the stepping.

How the two threads work together:

    main thread (desk_controller)          shade thread (this class)
    -----------------------------          -------------------------
    mover.move_to(100)  --- target --->    sleeps on a Condition until the
      returns at once                      target changes, then steps towards
                                           it in chunks of CHUNK half steps.
    mover.percent       <-- position --    After every chunk (~40 ms) it looks
      (for desk/actuators)                 at the target again, so a new
                                           command (a shade button!) takes
                                           effect at once, even halfway.

    The target is written by the main thread and read by the shade thread,
    so it is protected by a lock. A threading.Condition is a lock plus a
    "wake up" signal: notify() wakes the sleeping shade thread.
    The position is only written by the shade thread; the main thread only
    reads it.

    stop() asks the thread to finish. By default it first drives the shade
    back to OPEN, the start position every program assumes, and join() waits
    for that.
"""

import threading

CHUNK = 32   # half steps between two looks at the target (about 40 ms)


class ShadeMover:
    """Runs a Shade in a background thread; move_to() never blocks."""

    def __init__(self, shade):
        """Start the shade thread. shade is an actuators.shade.Shade object."""
        self.shade = shade
        self.error = None                      # exception that stopped the thread, if any
        self._target = shade.percent           # where the shade has to go (0–100 %)
        self._quit = False                     # stop() was called
        self._park = True                      # drive back to open before quitting
        self._cond = threading.Condition()     # protects the three fields above
        self._thread = threading.Thread(target=self._run, name="shade", daemon=True)
        self._thread.start()

    # --- called from the main thread ---------------------------------------
    @property
    def percent(self):
        """Current position, 0 % (open) – 100 % (closed)."""
        return self.shade.percent

    @property
    def target(self):
        """Position the shade is moving to (or standing at), 0–100 %."""
        with self._cond:
            return self._target

    @property
    def moving(self):
        """True while the shade is on its way to the target."""
        with self._cond:
            return self._steps_to_go() != 0

    @property
    def alive(self):
        """False if the thread has stopped (after stop() or an error)."""
        return self._thread.is_alive()

    def move_to(self, percent):
        """Set a new target, 0 % (open) – 100 % (closed). Returns immediately."""
        percent = max(0.0, min(100.0, float(percent)))
        with self._cond:
            self._target = percent
            self._cond.notify()                # wake the shade thread

    def stop(self, park=True, timeout=10):
        """End the thread; with park=True the shade first goes back to open."""
        with self._cond:
            self._quit = True
            self._park = park
            if park:
                self._target = 0.0
            self._cond.notify()
        self._thread.join(timeout)

    # --- the shade thread --------------------------------------------------
    def _steps_to_go(self):
        """Half steps from the current position to the target (call with the lock held)."""
        target = round(self._target * self.shade.full_steps / 100)
        return target - self.shade.position

    def _run(self):
        """Thread body: wait for a target, step towards it, repeat until stop()."""
        try:
            while True:
                with self._cond:
                    # Nothing to do: switch the coils off and sleep until notify()
                    while not self._quit and self._steps_to_go() == 0:
                        self.shade.release()
                        self._cond.wait()
                    todo = self._steps_to_go()
                    if self._quit and (not self._park or todo == 0):
                        return
                # Step WITHOUT holding the lock, so move_to() never has to wait
                self.shade.step(max(-CHUNK, min(CHUNK, todo)), release=False)
        except Exception as exc:  # noqa: BLE001 – report in the main thread instead of dying silently
            self.error = exc
        finally:
            try:
                self.shade.release()
            except Exception:  # noqa: BLE001 – best effort
                pass
