import csv

import requests
from bs4 import BeautifulSoup


def run():
    url = "https://wiki.superfamicom.org/65816-reference"

    response = requests.get(url)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, features="html.parser")
    tables = soup.find_all("table")
    table = tables[3]

    table_head = table.find("thead")
    head_row = table_head.find("tr")
    table_headers = [th.text.strip() for th in head_row.find_all("th")]

    table_body = table.find("tbody")
    body_rows = table_body.find_all("tr")
    table_rows = [[td.text.strip() for td in row.find_all("td")] for row in body_rows]

    with open("instructions.csv", "w") as f:
        writer = csv.writer(f)
        writer.writerow(table_headers)
        writer.writerows(table_rows)


if __name__ == "__main__":
    run()
