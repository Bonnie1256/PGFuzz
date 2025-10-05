import time
from subprocess import *
import os
import datetime

PGFUZZ_HOME = "/home/bonnie/PGFuzz/"

if os.path.isdir(PGFUZZ_HOME) is False:
    raise Exception("PGFUZZ_HOME variable is not set!")

ARDUPILOT_HOME = "/home/bonnie/PGFuzz/ardupilot_pgfuzz"

if os.path.isdir(ARDUPILOT_HOME) is False:
    raise Exception("ARDUPILOT_HOME variable is not set!")

open("restart.txt", "w").close()

c = 'gnome-terminal -- python ' + PGFUZZ_HOME + 'ArduPilot/open_simulator.py &'
handle = Popen(c, stdin=PIPE, stderr=PIPE, stdout=PIPE, shell=True)
print("opened open_simulator.py")
time.sleep(30)
# c = 'gnome-terminal -- python ' + PGFUZZ_HOME + 'ArduPilot/fuzzing.py &'
timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
logfile = 'fast_fuzz_' + timestamp + '.log'
c = 'gnome-terminal -- bash -lc "python ' + PGFUZZ_HOME + 'ArduPilot/fuzzing.py > ' + logfile + ' 2>&1"'
handle = Popen(c, stdin=PIPE, stderr=PIPE, stdout=PIPE, shell=True)
print("opened fuzzing.py")
while True:
    time.sleep(1)

    f = open("restart.txt", "r")

    if f.read() == "restart":
        f.close()
        open("restart.txt", "w").close()

        c = 'gnome-terminal -- python ' + PGFUZZ_HOME + 'ArduPilot/open_simulator.py &'
        handle = Popen(c, stdin=PIPE, stderr=PIPE, stdout=PIPE, shell=True)
        print("opened open_simulator.py")

