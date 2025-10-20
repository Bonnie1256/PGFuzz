import time
from subprocess import *
import os

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
time.sleep(90)
c = 'gnome-terminal -- python ' + PGFUZZ_HOME + 'ArduPilot/fuzzing.py &'
# c = 'gnome-terminal -- bash -lc "python ' + PGFUZZ_HOME + 'ArduPilot/fuzzing.py > original_fuzz1005_2.log 2>&1"'
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
	
