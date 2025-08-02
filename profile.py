import pstats
import cProfile

import pyximport
pyximport.install()

from pysnes import pysnes

# cProfile.runctx("pysnes.main()", globals(), locals(), "Profile.prof")
cProfile.run("pysnes.main()", "Profile.prof")

s = pstats.Stats("Profile.prof")
s.strip_dirs().sort_stats("time").print_stats()
