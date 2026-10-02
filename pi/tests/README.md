# Component tests

One stand-alone script per component, e.g. `test_ultrasonic.py`, `test_bh1750.py`,
`test_stepper.py`. Each script uses the pins from `../config.py` and prints or
shows what it measures, so the wiring can be checked one part at a time.

Run from the repository root with the virtual environment active:

```bash
python pi/tests/test_ultrasonic.py
```
