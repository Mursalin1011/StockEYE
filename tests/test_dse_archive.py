from datetime import date

from dse_screener.sources.dse_archive import parse_archive_html

# Trimmed copy of the real archive table markup (old.dsebd.org, 2026-09-30).
SAMPLE = """
<html><body>
<table class='table table-bordered background-white shares-table fixedHeader'>
  <thead><tr>
    <th>#</th><th>DATE</th><th>TRADING CODE</th><th>LTP*</th><th>HIGH</th><th>LOW</th>
    <th>OPENP*</th><th>CLOSEP*</th><th>YCP</th><th>TRADE</th><th>VALUE (mn)</th><th>VOLUME</th>
  </tr></thead>
  <tbody>
    <tr><td>1</td><td>2026-09-30</td><td><a href="displayCompany.php?name=GP" class='ab1'>
        GP      </a></td><td>241.9</td><td>242.9</td><td>241.5</td><td>242.9</td><td>241.6</td>
        <td>241.8</td><td>652</td><td>10.425</td><td>43,119</td></tr>
    <tr><td>2</td><td>2026-09-30</td><td><a href="displayCompany.php?name=1STPRIMFMF">1STPRIMFMF</a></td>
        <td>33.2</td><td>35.1</td><td>32.7</td><td>33.5</td><td>33.2</td><td>33.4</td>
        <td>1,759</td><td>57.596</td><td>1,695,892</td></tr>
  </tbody>
</table>
</body></html>
"""


def test_parses_rows_and_numbers():
    df = parse_archive_html(SAMPLE)
    assert list(df["code"]) == ["GP", "1STPRIMFMF"]
    gp = df.iloc[0]
    assert gp["date"] == date(2026, 9, 30)
    assert (gp["open"], gp["high"], gp["low"], gp["close"]) == (242.9, 242.9, 241.5, 241.6)
    assert gp["ltp"] == 241.9 and gp["ycp"] == 241.8
    assert gp["trades"] == 652 and gp["volume"] == 43_119
    assert df.iloc[1]["trades"] == 1_759 and df.iloc[1]["volume"] == 1_695_892


def test_no_trade_day_prices_become_missing():
    # GP on its 2026-08-12 record date: suspended, DSE prints zeros and carries the close
    html = SAMPLE.replace(
        "<td>241.9</td><td>242.9</td><td>241.5</td><td>242.9</td><td>241.6</td>\n        <td>241.8</td><td>652</td><td>10.425</td><td>43,119</td>",
        "<td>258.7</td><td>0</td><td>0</td><td>0</td><td>258.7</td>\n        <td>258.7</td><td>0</td><td>0</td><td>0</td>",
    )
    gp = parse_archive_html(html).iloc[0]
    assert gp["open"] != gp["open"] and gp["high"] != gp["high"]  # NaN
    assert gp["close"] == 258.7 and gp["volume"] == 0


def test_page_without_table_returns_empty():
    assert parse_archive_html("<html><body>No data</body></html>").empty
