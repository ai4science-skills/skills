import csv
rows=list(csv.DictReader(open("data/raw.csv")))
print(len(rows))
