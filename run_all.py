#!/usr/bin/env python3
"""Lanza los 4 harnesses en ventanas cmd independientes (Windows)."""
import subprocess, sys, pathlib, time

SCRIPTS = [
    ("Spring Boot", "run_springboot.py"),
    ("Angular", "run_angular.py"),
    ("React", "run_react.py"),
    ("Datos", "run_data.py"),
]

HERE = pathlib.Path(__file__).parent

print("Lanzando 4 ventanas en paralelo...")
for title, script in SCRIPTS:
    script_path = HERE / script

    # Construimos el comando como un solo string para evitar problemas de escape en Windows
    command = f'start "{title}" cmd /k "python "{script_path}" & echo. & echo Terminado. Pulsa ENTER para cerrar. & pause"'

    subprocess.Popen(
        command,
        shell=True,
        cwd=str(HERE),
    )
    time.sleep(0.5)

print("Hecho. Revisa las 4 ventanas abiertas.")
print("Cuando terminen, ejecuta: python merge_metrics.py")
