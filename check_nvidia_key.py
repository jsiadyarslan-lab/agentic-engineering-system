import os

key = os.getenv('NVIDIA_API_KEY')
if key:
    print(f"NVIDIA_API_KEY is SET (length: {len(key)})")
    print(f"Prefix: {key[:10]}...")
else:
    print("NVIDIA_API_KEY is NOT SET")
    print("Get one from: https://integrate.api.nvidia.com/")