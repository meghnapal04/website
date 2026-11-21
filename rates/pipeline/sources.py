"""Source registry: the single place that defines what is ingested.

Every series published on meghnapal.info/rates is listed here with its
official ECB Data Portal key, so each published number can be traced back
to its source (data lineage starts here).
"""

ECB_API = "https://data-api.ecb.europa.eu/service/data"
START = "2019-10-01"  # first publication date of the euro short-term rate (EUR STR)

# field name -> source definition
SERIES = {
    # Euro short-term rate (EUR STR) - daily, published by the ECB each TARGET2 business day
    "estr_rate": {
        "key": "EST/B.EU000A2X2A25.WT", "freq": "daily", "unit": "% p.a.",
        "label": "€STR, volume-weighted trimmed mean rate",
    },
    "estr_volume": {
        "key": "EST/B.EU000A2X2A25.TT", "freq": "daily", "unit": "EUR millions",
        "label": "€STR, total underlying transaction volume",
    },
    "estr_transactions": {
        "key": "EST/B.EU000A2X2A25.NT", "freq": "daily", "unit": "count",
        "label": "€STR, number of underlying transactions",
    },
    # ECB policy rate - used as the reference corridor for plausibility checks
    "dfr": {
        "key": "FM/D.U2.EUR.4F.KR.DFR.LEV", "freq": "daily", "unit": "% p.a.",
        "label": "ECB deposit facility rate",
    },
    # Euro area AAA government yield curve (Svensson model), spot rates
    "yc_aaa_2y": {
        "key": "YC/B.U2.EUR.4F.G_N_A.SV_C_YM.SR_2Y", "freq": "daily", "unit": "% p.a.",
        "label": "Euro area AAA government spot rate, 2-year",
    },
    "yc_aaa_5y": {
        "key": "YC/B.U2.EUR.4F.G_N_A.SV_C_YM.SR_5Y", "freq": "daily", "unit": "% p.a.",
        "label": "Euro area AAA government spot rate, 5-year",
    },
    "yc_aaa_10y": {
        "key": "YC/B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y", "freq": "daily", "unit": "% p.a.",
        "label": "Euro area AAA government spot rate, 10-year",
    },
    # EURIBOR - monthly averages as redistributed by the ECB
    "euribor_1m": {
        "key": "FM/M.U2.EUR.RT.MM.EURIBOR1MD_.HSTA", "freq": "monthly", "unit": "% p.a.",
        "label": "EURIBOR 1-month, monthly average",
    },
    "euribor_3m": {
        "key": "FM/M.U2.EUR.RT.MM.EURIBOR3MD_.HSTA", "freq": "monthly", "unit": "% p.a.",
        "label": "EURIBOR 3-month, monthly average",
    },
    "euribor_6m": {
        "key": "FM/M.U2.EUR.RT.MM.EURIBOR6MD_.HSTA", "freq": "monthly", "unit": "% p.a.",
        "label": "EURIBOR 6-month, monthly average",
    },
    "euribor_12m": {
        "key": "FM/M.U2.EUR.RT.MM.EURIBOR1YD_.HSTA", "freq": "monthly", "unit": "% p.a.",
        "label": "EURIBOR 12-month, monthly average",
    },
}


def url_for(key: str, start: str = START) -> str:
    return f"{ECB_API}/{key}?format=csvdata&detail=dataonly&startPeriod={start}"
