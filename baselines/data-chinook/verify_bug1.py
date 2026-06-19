"""Verifica que bug1_sales_genre.py produce el output correcto."""
import subprocess, sys, pandas as pd

result = subprocess.run([sys.executable, 'bug1_sales_genre.py'], capture_output=True, text=True)
if result.returncode != 0:
    print('ERROR ejecutando script:', result.stderr)
    sys.exit(1)

expected = pd.read_csv('expected/top_genres.csv')
actual = pd.read_csv('output_bug1.csv')

try:
    pd.testing.assert_frame_equal(actual.reset_index(drop=True), expected.reset_index(drop=True), check_dtype=False)
    print('OK: output correcto')
    sys.exit(0)
except AssertionError as e:
    print('FAIL: output incorrecto')
    print(e)
    sys.exit(1)
