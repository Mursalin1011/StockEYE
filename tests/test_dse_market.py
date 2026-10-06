from datetime import date

from dse_screener.sources.dse_market import parse_market_stats, parse_market_summary

# Trimmed copy of old.dsebd.org/market-statistics.php on 2026-10-06
SAMPLE = """<html><body><pre>
                      DHAKA STOCK EXCHANGE PLC.

                  TODAY'S SHARE MARKET : 2026-10-06
                  =================================


All Category

    ISSUES ADVANCED                 :                     79
    ISSUES DECLINED                 :                    270
    ISSUES UNCHANGED                :                     41
    TOTAL ISSUES TRADED             :                    390


A Category

    ISSUES ADVANCED                 :                     44
    ISSUES DECLINED                 :                    140
    ISSUES UNCHANGED                :                     15
    TOTAL ISSUES TRADED             :                    199

------------------------------------------------------------
TOTAL TRANSACTIONS

    A. NO. OF TRADES                :                 172178
    B. VOLUME(Nos.)                 :              180702291
    C. VALUE(Tk)                    :          5641757169.20



                    PRICES IN BLOCK TRANSACTIONS : 2026-10-06
                    =========================================

Instr Code    Max Price    Min Price    Trades    Quantity    Value(In Mn)

ASIATICLAB       114.00       114.00         1      131500          14.991
UNITEDFIN         17.80        17.80         1       37837           0.673
                                        ------    --------    ------------
                                            82    11876102         636.675

Total number of scrips traded in Block            =   33
</pre></body></html>
"""


def test_parses_official_totals_block_and_breadth():
    s = parse_market_stats(SAMPLE)
    assert s["date"] == date(2026, 10, 6)
    assert (s["trades"], s["volume"]) == (172_178, 180_702_291)
    assert round(s["value_mn"], 3) == 5641.757                   # what DSE's home page shows
    assert (s["block_trades"], s["block_volume"], s["block_value_mn"]) == (82, 11_876_102, 636.675)
    assert (s["advances"], s["declines"], s["unchanged"], s["issues_traded"]) == (79, 270, 41, 390)


def test_unreadable_page_is_none():
    assert parse_market_stats("<html><body>Not found</body></html>") is None


def test_market_summary_rows_are_kept_inside_the_range():
    # The API ignores a range outside its window and returns other days: those must be dropped
    text = ('{"rows":[{"date":"2026-10-06","dsex":5424.9,"dsexChange":-20.4,"ds30":2077.1,"ds30Change":-4.7,'
            '"totalTrade":172178,"totalValue":5641.757,"totalVolume":180702291,"marketCap":6761691.08},'
            '{"date":"2026-10-05","dsex":5445.3,"dsexChange":-37.1,"ds30":2081.8,"ds30Change":-3.5,'
            '"totalTrade":172753,"totalValue":5371.168,"totalVolume":180855154,"marketCap":6772519.79}]}')
    df = parse_market_summary(text, date(2026, 10, 1), date(2026, 10, 5))
    assert list(df["date"]) == [date(2026, 10, 5)]
    assert df.iloc[0]["value_mn"] == 5371.168 and df.iloc[0]["trades"] == 172_753
    assert parse_market_summary(text, date(2020, 1, 1), date(2020, 1, 31)).empty
