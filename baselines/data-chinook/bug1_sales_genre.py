"""
Tarea: devuelve las 5 géneros con más unidades vendidas.
Columnas esperadas: Genre, SalesCount
Ordenado descendente por SalesCount.
"""
import sqlite3
import pandas as pd

conn = sqlite3.connect('Chinook.db')

df = pd.read_sql_query("""
    SELECT g.Name as Genre, SUM(il.Quantity) as SalesCount
    FROM Genre g
    JOIN Track t ON g.GenreId = t.GenreId
    JOIN InvoiceLine il ON t.TrackId = il.InvoiceLineId
    GROUP BY g.Name
    ORDER BY SalesCount DESC
    LIMIT 5
""", conn)

conn.close()
print(df.to_string(index=False))
df.to_csv('output_bug1.csv', index=False)
