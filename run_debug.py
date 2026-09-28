import subprocess
result = subprocess.run(['python', 'debug_mission.py'], capture_output=True, text=True, timeout=120)
print(result.stdout)
print(result.stderr)
print("Return code:", result.returncode)