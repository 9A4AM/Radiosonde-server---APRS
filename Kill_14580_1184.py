#-------------------------------------------------------------------------------
# Name:        module1
# Purpose:
#
# Author:      9A4AM
#
# Created:     27.10.2024
# Copyright:   (c) 9A4AM 2024
# Licence:     <your licence>
#-------------------------------------------------------------------------------

import subprocess
import re

def kill_processes_using_ports(ports):
    for port in ports:
        # Pokreni netstat i filtriraj prema portu
        command = f"netstat -ano | findstr :{port}"
        result = subprocess.run(command, capture_output=True, text=True, shell=True)

        if result.stdout:
            # Prođi kroz rezultate i pronađi PID-ove
            for line in result.stdout.splitlines():
                # Regex za vađenje PID-a iz rezultata
                match = re.search(r'\s+(\d+)$', line)
                if match:
                    pid = match.group(1)
                    try:
                        # Ubije proces koristeći taskkill
                        print(f"Ubijam proces (PID: {pid}) koji koristi port {port}")
                        subprocess.run(f"taskkill /PID {pid} /F", shell=True)
                    except Exception as e:
                        print(f"Nepoznata greška prilikom gašenja procesa (PID: {pid}): {e}")
        else:
            print(f"Nema aktivnih procesa za port {port}")

# Definiraj portove koje želiš provjeriti
ports_to_check = [14580, 1184]

kill_processes_using_ports(ports_to_check)

