
from . import apu_v2
from . import apu

apu_v1 = apu.Apu()
apu_v2 = apu_v2.Apu()

for i in range(100000):
    print(f"{i}")

    if i == 722:
        print("break")

    apu_v1.tick()
    apu_v2.tick()

    assert str(apu_v1) == str(apu_v2)
