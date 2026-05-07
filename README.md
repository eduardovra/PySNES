# PySNES

## Virtualenv

```
snap install pypy3 --classic
/snap/bin/pypy3 -m venv venv
. venv/bin/activate
pip install -r requirements.txt
```

## Pypy setup

I tried using pypy from snap but it wasn't opening the window.
Then I switched to using the pre-compiled version from tarball.

https://doc.pypy.org/en/latest/install.html

## Running the emulator

```
uv run pysnes roms/game.sfc
```

### Running tests with uv

```
uv run pytest
```


## Building

### Inplace

```
uv run --python pypy@3.11 setup.py build_ext --inplace
```

### Release

```
uv build
```

## Overall architecture

The main loop would be something like:
  - CPU runs a bunch of instructions until N clock cycles is reached
  - Each N cycles a scanline is rendered to a buffer
    - Perhaps we can use H-COUNTER/V-COUNTER to control this. Still have to figure out the Clock cycles/H-COUNTER ratio
  - When all scanlines are drawn, update the screen and go back to scanline 0

I suppose this should work for both the CPU and APU, except the APU will be dealing with outputing audio instead.
The APU also needs to update the timers counters after every instruction.


## Processor tests

https://github.com/TomHarte/ProcessorTests
