"""Verifica que feat1_customer_ranking.py produce el output correcto."""
import subprocess, sys, pandas as pd

result = subprocess.run([sys.executable, 'feat1_customer_ranking.py'], capture_output=True, text=True)
if result.returncode != 0:
    print('ERROR ejecutando script:', result.stderr)
    sys.exit(1)

expected = pd.read_csv('expected/customer_ranking.csv')
actual = pd.read_csv('output_feat1.csv')

if actual.empty:
    print('FAIL: el script devuelve un DataFrame vacío (implementación pendiente)')
    sys.exit(1)

try:
    for col in ['Country', 'CustomerId', 'FirstName', 'LastName', 'TotalPurchases', 'Rank']:
        if col not in actual.columns:
            print(f'FAIL: columna "{col}" no encontrada. Columnas actuales: {actual.columns.tolist()}')
            sys.exit(1)

    actual_sorted = actual.sort_values(['Country', 'Rank']).reset_index(drop=True)
    expected_sorted = expected.sort_values(['Country', 'Rank']).reset_index(drop=True)

    pd.testing.assert_frame_equal(
        actual_sorted[['Country', 'CustomerId', 'TotalPurchases', 'Rank']].reset_index(drop=True),
        expected_sorted[['Country', 'CustomerId', 'TotalPurchases', 'Rank']].reset_index(drop=True),
        check_dtype=False, atol=0.01
    )
    print('OK: output correcto')
    sys.exit(0)
except AssertionError as e:
    print('FAIL: output incorrecto')
    print(e)
    sys.exit(1)
