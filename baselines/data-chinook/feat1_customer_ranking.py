"""
Tarea: rankear clientes por total comprado dentro de su país usando window functions.
Columnas requeridas: Country, CustomerId, FirstName, LastName, TotalPurchases, Rank
- TotalPurchases = suma de Invoice.Total por cliente, redondeada a 2 decimales
- Rank: RANK() dentro del país ordenado por TotalPurchases DESC
- Orden final: Country ASC, Rank ASC
"""
import sqlite3
import pandas as pd

conn = sqlite3.connect('Chinook.db')

# TODO: implementa la query SQL con window function RANK()
df = pd.read_sql_query("""
    SELECT '' as Country, 0 as CustomerId, '' as FirstName, '' as LastName,
           0.0 as TotalPurchases, 0 as Rank
    WHERE 1=0
""", conn)

conn.close()
print(df.to_string(index=False))
df.to_csv('output_feat1.csv', index=False)
