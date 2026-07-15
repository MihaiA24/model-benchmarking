# Developer Brief

Repair the sales-by-genre report in this repository.

Running `python3 sales_by_genre.py --input data/sales.json --output sales-by-genre.csv` must write the five genres with the greatest total sold quantity. The CSV columns are exactly `Genre,UnitsSold`; rows are ordered by quantity descending and then genre name ascending. Quantities from every sold track must contribute to its genre.

Preserve the input fixture, command-line interface, output format, and deterministic ordering. Change only `sales_by_genre.py`.
