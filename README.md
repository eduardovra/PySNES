# PySNES

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
