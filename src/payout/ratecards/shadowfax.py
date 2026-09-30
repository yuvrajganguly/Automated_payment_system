"""Shadowfax Kolkata LMA ratecard — what we pay a rider per order, by pincode.

Source: Shadowfax_ratecard.pdf, "Kolkata LMA Rates — Grouped by Cluster",
already ₹1 below Shadowfax's own rate. 193 pincodes, 42 clusters. Rupees per
order; the migration and the seed turn them into paise. This is the seed only:
the live card is ``company_pincode_rates`` and the office replaces it from
Admin → Companies without a code change.
"""

from __future__ import annotations

import csv
import io

EFFECTIVE_FROM = "2000-01-01"  # the first card: in force for every order date

RATECARD_CSV = """\
cluster,pincode,RVP,COD,PPD,SDD,Club
CCU_Ballygunj,700017,15,15,14,19,7
CCU_Ballygunj,700019,14,14,13,18,7
CCU_Barrackpore,700049,15,15,14,19,7
CCU_Barrackpore,700051,15,15,14,19,7
CCU_Barrackpore,700110,15,15,14,19,7
CCU_Barrackpore,700111,14,14,13,18,7
CCU_Barrackpore,700112,14,14,13,18,7
CCU_Barrackpore,700113,14,14,13,18,7
CCU_Barrackpore,700114,14,14,13,18,7
CCU_Barrackpore,700115,14,14,13,18,7
CCU_Barrackpore,700116,14,14,13,18,7
CCU_Barrackpore,700117,14,14,13,18,7
CCU_Barrackpore,700134,14,14,13,18,7
CCU_Belgharia,700056,14,14,13,18,7
CCU_Belgharia,700057,14,14,13,18,7
CCU_Belgharia,700058,14,14,13,18,7
CCU_Belgharia,700083,14,14,13,18,7
CCU_Belgharia,700109,14,14,13,18,7
CCU_Belur,711107,14,14,13,18,7
CCU_Belur,711120,14,14,13,18,7
CCU_Belur,711201,14,14,13,18,7
CCU_Belur,711202,14,14,13,18,7
CCU_Belur,711203,14,14,13,18,7
CCU_Belur,711204,14,14,13,18,7
CCU_Belur,711205,14,14,13,18,7
CCU_Belur,711206,14,14,13,18,7
CCU_Belur,711224,14,14,13,18,7
CCU_Belur,711227,14,14,13,18,7
CCU_Bhawanipur,700020,14,14,13,18,7
CCU_Bhawanipur,700025,14,14,13,18,7
CCU_Bhawanipur,700026,14,14,13,18,7
CCU_Budgebudge,700137,14,14,13,18,7
CCU_Budgebudge,700138,14,14,13,18,7
CCU_Budgebudge,743318,14,14,13,18,7
CCU_Budgebudge,743319,20,20,19,24,7
CCU_Dhakuria,700029,14,14,13,18,7
CCU_Dhakuria,700033,14,14,13,18,7
CCU_Dhakuria,700045,14,14,13,18,7
CCU_Dhakuria,700068,14,14,13,18,7
CCU_Dhakuria,700095,14,14,13,18,7
CCU_Dhapa,700039,14.5,14.5,13.5,18.5,7
CCU_Dhapa,700046,14.5,14.5,13.5,18.5,7
CCU_Dhapa,700100,14.5,14.5,13.5,18.5,7
CCU_Dhulagarh,711302,14,14,13,18,7
CCU_Dhulagarh,711304,15.5,15.5,14.5,19.5,7
CCU_Dhulagarh,711313,14,14,13,18,7
CCU_Dhulagarh,711317,14,14,13,18,7
CCU_Dhulagarh,711411,14,14,13,18,7
CCU_Dumdum,700028,14,14,13,18,7
CCU_Dumdum,700030,14,14,13,18,7
CCU_Dumdum,700065,14,14,13,18,7
CCU_Dumdum,700074,14,14,13,18,7
CCU_Dumdum,700077,14,14,13,18,7
CCU_Dunlop,700035,14,14,13,18,7
CCU_Dunlop,700036,14,14,13,18,7
CCU_Dunlop,700050,14,14,13,18,7
CCU_Dunlop,700076,14,14,13,18,7
CCU_Dunlop,700090,14,14,13,18,7
CCU_Dunlop,700108,14,14,13,18,7
CCU_GARIA,700094,14,14,13,18,7
CCU_GARIA,700152,14,14,13,18,7
CCU_Ghatakpukur_E,700157,14.5,14.5,13.5,18.5,7
CCU_Ghatakpukur_E,700159,15.5,15.5,14.5,19.5,7
CCU_Ghatakpukur_E,700162,14,14,13,18,7
CCU_GirishPark,700001,18,18,17,22,7
CCU_GirishPark,700005,16,16,15,20,7
CCU_GirishPark,700006,16,16,15,20,7
CCU_GirishPark,700007,16,16,15,20,7
CCU_GirishPark,700062,16,16,15,20,7
CCU_Howrah_N,711001,14.5,14.5,13.5,18.5,7
CCU_Howrah_N,711101,14.5,14.5,13.5,18.5,7
CCU_Howrah_N,711102,14.5,14.5,13.5,18.5,7
CCU_Howrah_N,711323,14.5,14.5,13.5,18.5,7
CCU_Howrah_N,711327,14.5,14.5,13.5,18.5,7
CCU_Howrah_N,711402,14.5,14.5,13.5,18.5,7
CCU_Kankurgachi,700009,14,14,13,18,7
CCU_Kankurgachi,700011,14,14,13,18,7
CCU_Kankurgachi,700054,14,14,13,18,7
CCU_Kankurgachi,700067,14,14,13,18,7
CCU_Kestopur,700048,14,14,13,18,7
CCU_Kestopur,700055,14,14,13,18,7
CCU_Kestopur,700089,14,14,13,18,7
CCU_Kestopur,700101,14,14,13,18,7
CCU_Khiddirpur,700021,16,16,15,20,7
CCU_Khiddirpur,700022,16,16,15,20,7
CCU_Khiddirpur,700023,16,16,15,20,7
CCU_Khiddirpur,700027,16,16,15,20,7
CCU_Khiddirpur,700043,16,16,15,20,7
CCU_Laketown_N,700052,15,15,14,19,7
CCU_Laketown_N,700059,14,14,13,18,7
CCU_Laketown_N,700079,14,14,13,18,7
CCU_Laketown_N,700080,14,14,13,18,7
CCU_Laketown_N,700081,15,15,14,19,7
CCU_Madhyamgram,700129,14,14,13,18,7
CCU_Madhyamgram,700130,14,14,13,18,7
CCU_Madhyamgram,700131,14,14,13,18,7
CCU_Madhyamgram,700132,14,14,13,18,7
CCU_Madhyamgram,700133,14,14,13,18,7
CCU_Madhyamgram,700155,14,14,13,18,7
CCU_Madhyamgram,700158,14,14,13,18,7
CCU_Madhyamgram,743250,16,16,15,20,7
CCU_Maheshtala,700139,16,16,15,20,7
CCU_Maheshtala,700140,14,14,13,18,7
CCU_Maheshtala,700141,15,15,14,19,7
CCU_Maheshtala,700142,14,14,13,18,7
CCU_Maheshtala,700143,14,14,13,18,7
CCU_Maheshtala,743352,14,14,13,18,7
CCU_Makardaha_N,711113,14.5,14.5,13.5,18.5,7
CCU_Makardaha_N,711403,14,14,13,18,7
CCU_Makardaha_N,711405,14.5,14.5,13.5,18.5,7
CCU_Makardaha_N,711409,14,14,13,18,7
CCU_Makardaha_N,711416,14,14,13,18,7
CCU_Metiabruz,700018,15,15,14,19,7
CCU_Metiabruz,700024,14,14,13,18,7
CCU_Metiabruz,700044,15,15,14,19,7
CCU_Metiabruz,700066,22,22,21,26,7
CCU_Metropolitan,700010,14,14,13,18,7
CCU_Metropolitan,700015,14,14,13,18,7
CCU_Metropolitan,700085,14,14,13,18,7
CCU_Metropolitan,700105,14,14,13,18,7
CCU_Moulali,700000,16.5,16.5,15.5,20.5,7
CCU_Moulali,700012,16.5,16.5,15.5,20.5,7
CCU_Moulali,700013,16.5,16.5,15.5,20.5,7
CCU_Moulali,700069,16.5,16.5,15.5,20.5,7
CCU_Moulali,700072,16.5,16.5,15.5,20.5,7
CCU_Moulali,700073,16.5,16.5,15.5,20.5,7
CCU_Naktala_E,700047,14,14,13,18,7
CCU_Naktala_E,700070,14,14,13,18,7
CCU_Naktala_E,700086,14,14,13,18,7
CCU_Naktala_E,700092,14,14,13,18,7
CCU_Naktala_E,700096,14,14,13,18,7
CCU_Narayanpur,700136,14,14,13,18,7
CCU_Narayanpur,700161,14,14,13,18,7
CCU_Narendrapur,700084,14,14,13,18,7
CCU_Narendrapur,700103,14,14,13,18,7
CCU_Narendrapur,700149,14,14,13,18,7
CCU_Narendrapur,700151,15,15,14,19,7
CCU_Narendrapur,700153,14,14,13,18,7
CCU_Narendrapur,700154,15,15,14,19,7
CCU_Newtown,700156,14,14,13,18,7
CCU_Newtown,700160,14,14,13,18,7
CCU_Newtown,700163,14,14,13,18,7
CCU_Parkstreet,700014,16,16,15,20,7
CCU_Parkstreet,700016,16,16,15,20,7
CCU_Parkstreet,700071,16,16,15,20,7
CCU_Parkstreet,700087,16,16,15,20,7
CCU_Parnasree,700034,14,14,13,18,7
CCU_Parnasree,700038,14,14,13,18,7
CCU_Parnasree,700053,14,14,13,18,7
CCU_Parnasree,700060,14,14,13,18,7
CCU_Parnasree,700088,14,14,13,18,7
CCU_Parnasree,743301,14,14,13,18,7
CCU_Rajarhat,700135,15,15,14,19,7
CCU_Ruby,700099,14,14,13,18,7
CCU_Ruby,700107,14,14,13,18,7
CCU_Salkia,711105,14,14,13,18,7
CCU_Salkia,711106,14,14,13,18,7
CCU_Salkia,711108,14,14,13,18,7
CCU_Salkia,711114,14,14,13,18,7
CCU_Saltlake,700064,14,14,13,18,7
CCU_Saltlake,700097,14,14,13,18,7
CCU_Saltlake,700098,14,14,13,18,7
CCU_Saltlake,700106,14,14,13,18,7
CCU_Shakerbazar,700008,14.5,14.5,13.5,18.5,7
CCU_Shakerbazar,700061,14,14,13,18,7
CCU_Shakerbazar,700063,14,14,13,18,7
CCU_Shakerbazar,700104,14,14,13,18,7
CCU_Shyambazar,700002,14,14,13,18,7
CCU_Shyambazar,700003,14,14,13,18,7
CCU_Shyambazar,700004,14,14,13,18,7
CCU_Shyambazar,700037,14,14,13,18,7
CCU_Sonarpur,700145,15.5,15.5,14.5,19.5,7
CCU_Sonarpur,700146,14.5,14.5,13.5,18.5,7
CCU_Sonarpur,700147,14.5,14.5,13.5,18.5,7
CCU_Sonarpur,700148,14,14,13,18,7
CCU_Sonarpur,700150,15.5,15.5,14.5,19.5,7
CCU_Technopolis,700091,14,14,13,18,7
CCU_Technopolis,700102,14,14,13,18,7
CCU_Tiljala_N,700031,14,14,13,18,7
CCU_Tiljala_N,700032,14,14,13,18,7
CCU_Tiljala_N,700042,14,14,13,18,7
CCU_Tiljala_N,700075,14,14,13,18,7
CCU_Tiljala_N,700078,14,14,13,18,7
CCU_Titagarh,700118,14,14,13,18,7
CCU_Titagarh,700119,14,14,13,18,7
CCU_Titagarh,700120,15,15,14,19,7
CCU_Titagarh,700121,15,15,14,19,7
CCU_Titagarh,700122,14,14,13,18,7
CCU_Titagarh,700123,14,14,13,18,7
CCU_Tollygunge,700040,14,14,13,18,7
CCU_Tollygunge,700041,14,14,13,18,7
CCU_Tollygunge,700082,14,14,13,18,7
CCU_Tollygunge,700093,14,14,13,18,7
"""


def rows() -> list[dict]:
    """Parsed rows: cluster, pincode (str), and the five rates in paise."""
    out = []
    for r in csv.DictReader(io.StringIO(RATECARD_CSV)):
        out.append(
            {
                "cluster": r["cluster"].strip(),
                "pincode": r["pincode"].strip(),
                **{
                    k.lower(): round(float(r[k]) * 100)
                    for k in ("RVP", "COD", "PPD", "SDD", "Club")
                },
            }
        )
    return out
