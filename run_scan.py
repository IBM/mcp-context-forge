import subprocess
import sys

exclude = r'(?x)( package-lock\.json$ |Cargo\.lock$ |uv\.lock$ |go\.sum$ |mcpgateway/sri_hashes\.json$ |^.*venv.* |^.*node_modules.* )|^\.secrets\.baseline$'
cmd = [
    r".\ds_venv\Scripts\detect-secrets.exe",
    "scan",
    "--update", ".secrets.baseline",
    "--use-all-plugins",
    "--exclude-files", exclude
]
print("Running:", " ".join(cmd))
result = subprocess.run(cmd)
print("Exit code:", result.returncode)
