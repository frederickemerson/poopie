// GENERATED from the OpenSky Network public aircraft database
// (https://opensky-network.org/datasets/metadata/aircraftDatabase.csv) by
// scripts/gen_fleet.py. Real registrations, real manufacturer serial numbers,
// real operators. Regenerate rather than hand-editing.
//
// PROVENANCE NOTE, surfaced in the UI: OpenSky carries no equipment, modification
// or supplemental-type-certificate data. Those fields are therefore absent, not
// unset-and-guessable, which is exactly why equipment-conditioned ADs resolve to
// 86 cells of which some can only be CANNOT_DETERMINE.

import type { Source } from "./contract";

export interface FleetAircraft {
  readonly tail_number: string;
  readonly icao24: string;
  readonly manufacturer: string;
  readonly model: string;
  readonly typecode: string;
  readonly serial_number: string;
  readonly operator: string;
  readonly built_year: number | null;
  /** OpenSky holds no equipment list. Always null; never inferred. */
  readonly equipment: readonly string[] | null;
  /** OpenSky holds no modification or STC record. Always null; never inferred. */
  readonly modification: readonly string[] | null;
}

export const FLEET_SOURCE: Source = "opensky";

export const FLEET_PROVENANCE = {
  dataset: "OpenSky Network public aircraft database",
  url: "https://opensky-network.org/datasets/metadata/aircraftDatabase.csv",
  retrieved: "2026-10-31",
  aircraft: 86,
  operators: 7,
  absent_fields: ["equipment", "modification", "part_number"] as const,
  caveat:
    "Registration, manufacturer serial number, model and operator are as published by OpenSky. " +
    "The dataset carries no equipment, modification or STC record, so every equipment-conditioned " +
    "applicability rule resolves to CANNOT_DETERMINE rather than a guess.",
} as const;

const RAW: readonly Omit<FleetAircraft, "equipment" | "modification">[] = [
  {
    "tail_number": "N700UW",
    "icao24": "a95665",
    "manufacturer": "Airbus Industrie",
    "model": "A319-112",
    "typecode": "A319",
    "serial_number": "0885",
    "operator": "American Airlines",
    "built_year": 1998
  },
  {
    "tail_number": "N721UW",
    "icao24": "a9a91a",
    "manufacturer": "Airbus Industrie",
    "model": "A319-112",
    "typecode": "A319",
    "serial_number": "1095",
    "operator": "American Airlines",
    "built_year": 1999
  },
  {
    "tail_number": "N752US",
    "icao24": "aa234a",
    "manufacturer": "Airbus Industrie",
    "model": "A319-112",
    "typecode": "A319",
    "serial_number": "1319",
    "operator": "American Airlines",
    "built_year": 2000
  },
  {
    "tail_number": "N830AW",
    "icao24": "ab586f",
    "manufacturer": "Airbus Industrie",
    "model": "A319-132",
    "typecode": "A319",
    "serial_number": "1565",
    "operator": "American Airlines",
    "built_year": null
  },
  {
    "tail_number": "N70020",
    "icao24": "a95745",
    "manufacturer": "Airbus",
    "model": "A319-115",
    "typecode": "A319",
    "serial_number": "6263",
    "operator": "American Airlines",
    "built_year": 2014
  },
  {
    "tail_number": "N647AW",
    "icao24": "a87f51",
    "manufacturer": "Airbus Industrie",
    "model": "A320-232",
    "typecode": "A320",
    "serial_number": "762",
    "operator": "American Airlines",
    "built_year": 1997
  },
  {
    "tail_number": "N103US",
    "icao24": "a011ac",
    "manufacturer": "Airbus Industrie",
    "model": "A320-214",
    "typecode": "A320",
    "serial_number": "0861",
    "operator": "American Airlines",
    "built_year": 1999
  },
  {
    "tail_number": "N105UW",
    "icao24": "a0191e",
    "manufacturer": "Airbus Industrie",
    "model": "A320-214",
    "typecode": "A320",
    "serial_number": "0868",
    "operator": "American Airlines",
    "built_year": 1999
  },
  {
    "tail_number": "N658AW",
    "icao24": "a8aa87",
    "manufacturer": "Airbus Industrie",
    "model": "A320-232",
    "typecode": "A320",
    "serial_number": "1110",
    "operator": "American Airlines",
    "built_year": 1999
  },
  {
    "tail_number": "N117UW",
    "icao24": "a0480b",
    "manufacturer": "Airbus Industrie",
    "model": "A320-214",
    "typecode": "A320",
    "serial_number": "1224",
    "operator": "American Airlines",
    "built_year": 2000
  },
  {
    "tail_number": "N661AW",
    "icao24": "a8b805",
    "manufacturer": "Airbus Industrie",
    "model": "A320-232",
    "typecode": "A320",
    "serial_number": "1284",
    "operator": "American Airlines",
    "built_year": 2000
  },
  {
    "tail_number": "N124US",
    "icao24": "a06461",
    "manufacturer": "Airbus Industrie",
    "model": "A320-214",
    "typecode": "A320",
    "serial_number": "1314",
    "operator": "American Airlines",
    "built_year": 2000
  },
  {
    "tail_number": "N669AW",
    "icao24": "a8d5bd",
    "manufacturer": "Airbus",
    "model": "A320-232",
    "typecode": "A320",
    "serial_number": "1792",
    "operator": "American Airlines",
    "built_year": 2002
  },
  {
    "tail_number": "N127UW",
    "icao24": "a06f8a",
    "manufacturer": "Airbus",
    "model": "A320-214",
    "typecode": "A320",
    "serial_number": "4202",
    "operator": "American Airlines",
    "built_year": 2010
  },
  {
    "tail_number": "N191UW",
    "icao24": "a16db9",
    "manufacturer": "Airbus Industrie",
    "model": "A321-211",
    "typecode": "A321",
    "serial_number": "1447",
    "operator": "American Airlines",
    "built_year": 2001
  },
  {
    "tail_number": "N104NN",
    "icao24": "a014c9",
    "manufacturer": "Airbus",
    "model": "A321-231",
    "typecode": "A321",
    "serial_number": "5895",
    "operator": "American Airlines",
    "built_year": 2013
  },
  {
    "tail_number": "N908AA",
    "icao24": "ac8ce5",
    "manufacturer": "Airbus",
    "model": "A321-231",
    "typecode": "A321",
    "serial_number": "7775",
    "operator": "American Airlines",
    "built_year": 2017
  },
  {
    "tail_number": "N655AA",
    "icao24": "a89f4e",
    "manufacturer": "Boeing",
    "model": "757-223",
    "typecode": "B752",
    "serial_number": "24613",
    "operator": "American Airlines",
    "built_year": 1991
  },
  {
    "tail_number": "N659AA",
    "icao24": "a8ae2a",
    "manufacturer": "Boeing",
    "model": "757-223",
    "typecode": "B752",
    "serial_number": "24617",
    "operator": "American Airlines",
    "built_year": 1992
  },
  {
    "tail_number": "N401DZ",
    "icao24": "a4b0bb",
    "manufacturer": "Airbus",
    "model": "A330-941",
    "typecode": "A339",
    "serial_number": "1915",
    "operator": "Delta Air Lines",
    "built_year": 2019
  },
  {
    "tail_number": "N404DX",
    "icao24": "a4bbde",
    "manufacturer": "Airbus",
    "model": "A330-941",
    "typecode": "A339",
    "serial_number": "01935",
    "operator": "Delta Air Lines",
    "built_year": 2019
  },
  {
    "tail_number": "N406DX",
    "icao24": "a4c34c",
    "manufacturer": "Airbus",
    "model": "A330-941",
    "typecode": "A339",
    "serial_number": "1953",
    "operator": "Delta Air Lines",
    "built_year": 2020
  },
  {
    "tail_number": "N409DX",
    "icao24": "a4ce71",
    "manufacturer": "Airbus",
    "model": "A330-941",
    "typecode": "A339",
    "serial_number": "1983",
    "operator": "Delta Air Lines",
    "built_year": 2021
  },
  {
    "tail_number": "N412DX",
    "icao24": "a4dbef",
    "manufacturer": "Airbus",
    "model": "A330-941",
    "typecode": "A339",
    "serial_number": "1994",
    "operator": "Delta Air Lines",
    "built_year": 2022
  },
  {
    "tail_number": "N415DX",
    "icao24": "a4e714",
    "manufacturer": "Airbus Sas",
    "model": "A330-941",
    "typecode": "A339",
    "serial_number": "1997",
    "operator": "Delta Air Lines",
    "built_year": null
  },
  {
    "tail_number": "N417DX",
    "icao24": "a4ee82",
    "manufacturer": "Airbus",
    "model": "A330-941",
    "typecode": "A339",
    "serial_number": "2000",
    "operator": "Delta Air Lines",
    "built_year": 2022
  },
  {
    "tail_number": "N420DX",
    "icao24": "a4fc00",
    "manufacturer": "Airbus Sas",
    "model": "A330-941",
    "typecode": "A339",
    "serial_number": "2021",
    "operator": "Delta Air Lines",
    "built_year": null
  },
  {
    "tail_number": "N314DN",
    "icao24": "a35605",
    "manufacturer": "Airbus",
    "model": "A321-211",
    "typecode": "A321",
    "serial_number": "7281",
    "operator": "Delta Air Lines",
    "built_year": 2016
  },
  {
    "tail_number": "N357DN",
    "icao24": "a3ff26",
    "manufacturer": "Airbus",
    "model": "A321-211",
    "typecode": "A321",
    "serial_number": "8339",
    "operator": "Delta Air Lines",
    "built_year": 2018
  },
  {
    "tail_number": "N390DN",
    "icao24": "a48321",
    "manufacturer": "Airbus",
    "model": "A321-211",
    "typecode": "A321",
    "serial_number": "9066",
    "operator": "Delta Air Lines",
    "built_year": 2019
  },
  {
    "tail_number": "N129DN",
    "icao24": "a07579",
    "manufacturer": "Airbus",
    "model": "A321-211",
    "typecode": "A321",
    "serial_number": "10315",
    "operator": "Delta Air Lines",
    "built_year": 2021
  },
  {
    "tail_number": "N608DA",
    "icao24": "a7e543",
    "manufacturer": "Boeing",
    "model": "757-232",
    "typecode": "B752",
    "serial_number": "22815",
    "operator": "Delta Air Lines",
    "built_year": 1985
  },
  {
    "tail_number": "N651DL",
    "icao24": "a890c7",
    "manufacturer": "Boeing",
    "model": "757-232",
    "typecode": "B752",
    "serial_number": "24391",
    "operator": "Delta Air Lines",
    "built_year": 1989
  },
  {
    "tail_number": "N655DL",
    "icao24": "a89fa3",
    "manufacturer": "Boeing",
    "model": "757-232",
    "typecode": "B752",
    "serial_number": "24395",
    "operator": "Delta Air Lines",
    "built_year": 1990
  },
  {
    "tail_number": "N711ZX",
    "icao24": "a98219",
    "manufacturer": "Boeing",
    "model": "757-231",
    "typecode": "B752",
    "serial_number": "28481",
    "operator": "Delta Air Lines",
    "built_year": 1997
  },
  {
    "tail_number": "N364NW",
    "icao24": "a41c69",
    "manufacturer": "Airbus Industrie",
    "model": "A320-212",
    "typecode": "A320",
    "serial_number": "0962",
    "operator": "Delta Air Lines",
    "built_year": 1999
  },
  {
    "tail_number": "N355NB",
    "icao24": "a3f88e",
    "manufacturer": "Airbus",
    "model": "A319-114",
    "typecode": "A319",
    "serial_number": "1839",
    "operator": "Delta Air Lines",
    "built_year": 2002
  },
  {
    "tail_number": "N841UA",
    "icao24": "ab8553",
    "manufacturer": "Airbus Industrie",
    "model": "A319-131",
    "typecode": "A319",
    "serial_number": "1545",
    "operator": "United Airlines",
    "built_year": 2001
  },
  {
    "tail_number": "N875UA",
    "icao24": "ac0aac",
    "manufacturer": "Airbus",
    "model": "A319-132",
    "typecode": "A319",
    "serial_number": "2200",
    "operator": "United Airlines",
    "built_year": null
  },
  {
    "tail_number": "N5867U",
    "icao24": "a78f92",
    "manufacturer": "Airbus",
    "model": "A319-132",
    "typecode": "A319",
    "serial_number": "2631",
    "operator": "United Airlines",
    "built_year": null
  },
  {
    "tail_number": "N899UA",
    "icao24": "ac6886",
    "manufacturer": "Airbus",
    "model": "A319-132",
    "typecode": "A319",
    "serial_number": "3342",
    "operator": "United Airlines",
    "built_year": 2007
  },
  {
    "tail_number": "N411UA",
    "icao24": "a4d99a",
    "manufacturer": "Airbus Industrie",
    "model": "A320-232",
    "typecode": "A320",
    "serial_number": "464",
    "operator": "United Airlines",
    "built_year": 1994
  },
  {
    "tail_number": "N482UA",
    "icao24": "a5f1ca",
    "manufacturer": "Airbus Industrie",
    "model": "A320-232",
    "typecode": "A320",
    "serial_number": "1584",
    "operator": "United Airlines",
    "built_year": 2001
  },
  {
    "tail_number": "N1914U",
    "icao24": "a16ed9",
    "manufacturer": "Airbus",
    "model": "A320-232",
    "typecode": "A320",
    "serial_number": "2223",
    "operator": "United Airlines",
    "built_year": null
  },
  {
    "tail_number": "N1902U",
    "icao24": "a16adc",
    "manufacturer": "Airbus",
    "model": "A320-232",
    "typecode": "A320",
    "serial_number": "2714",
    "operator": "United Airlines",
    "built_year": null
  },
  {
    "tail_number": "N503UA",
    "icao24": "a646d8",
    "manufacturer": "Boeing",
    "model": "757-222",
    "typecode": "B752",
    "serial_number": "24624",
    "operator": "United Airlines",
    "built_year": 1989
  },
  {
    "tail_number": "N33103",
    "icao24": "a39bfa",
    "manufacturer": "Boeing",
    "model": "757-224",
    "typecode": "B752",
    "serial_number": "27293",
    "operator": "United Airlines",
    "built_year": 1994
  },
  {
    "tail_number": "N17133",
    "icao24": "a11fc1",
    "manufacturer": "Boeing",
    "model": "757-224",
    "typecode": "B752",
    "serial_number": "29282",
    "operator": "United Airlines",
    "built_year": 1998
  },
  {
    "tail_number": "N57862",
    "icao24": "a76f66",
    "manufacturer": "Boeing",
    "model": "757-33N",
    "typecode": "B753",
    "serial_number": "32586",
    "operator": "United Airlines",
    "built_year": 2001
  },
  {
    "tail_number": "N78866",
    "icao24": "aab187",
    "manufacturer": "Boeing",
    "model": "757-33N",
    "typecode": "B753",
    "serial_number": "32591",
    "operator": "United Airlines",
    "built_year": 2002
  },
  {
    "tail_number": "A7-ADA",
    "icao24": "06a016",
    "manufacturer": "Airbus",
    "model": "A320-232",
    "typecode": "A320",
    "serial_number": "1566",
    "operator": "Qatar Airways",
    "built_year": 2001
  },
  {
    "tail_number": "A7-AHB",
    "icao24": "06a088",
    "manufacturer": "Airbus",
    "model": "A320 232",
    "typecode": "A320",
    "serial_number": "4130",
    "operator": "Qatar Airways",
    "built_year": 2009
  },
  {
    "tail_number": "A7-AHG",
    "icao24": "06a091",
    "manufacturer": "Airbus",
    "model": "A320 232",
    "typecode": "A320",
    "serial_number": "4615",
    "operator": "Qatar Airways",
    "built_year": 2011
  },
  {
    "tail_number": "A7-AHS",
    "icao24": "06a09a",
    "manufacturer": "Airbus",
    "model": "A320 232",
    "typecode": "A320",
    "serial_number": "5010",
    "operator": "Qatar Airways",
    "built_year": 2012
  },
  {
    "tail_number": "A7-LAG",
    "icao24": "06a1e1",
    "manufacturer": "Airbus",
    "model": "A320 214SL",
    "typecode": "A320",
    "serial_number": "6717",
    "operator": "Qatar Airways",
    "built_year": 2015
  },
  {
    "tail_number": "A7-AEB",
    "icao24": "06a032",
    "manufacturer": "Airbus",
    "model": "A330 302",
    "typecode": "A333",
    "serial_number": "637",
    "operator": "Qatar Airways",
    "built_year": 2004
  },
  {
    "tail_number": "A7-AEF",
    "icao24": "06a040",
    "manufacturer": "Airbus",
    "model": "A330 302",
    "typecode": "A333",
    "serial_number": "721",
    "operator": "Qatar Airways",
    "built_year": 2006
  },
  {
    "tail_number": "A7-AEI",
    "icao24": "06a04a",
    "manufacturer": "Airbus",
    "model": "A330 302",
    "typecode": "A333",
    "serial_number": "813",
    "operator": "Qatar Airways",
    "built_year": 2006
  },
  {
    "tail_number": "A7-AEO",
    "icao24": "06a061",
    "manufacturer": "Airbus",
    "model": "A330 302",
    "typecode": "A333",
    "serial_number": "918",
    "operator": "Qatar Airways",
    "built_year": 2008
  },
  {
    "tail_number": "A7-ACC",
    "icao24": "06a01e",
    "manufacturer": "Airbus",
    "model": "A330-202",
    "typecode": "A332",
    "serial_number": "511",
    "operator": "Qatar Airways",
    "built_year": 2003
  },
  {
    "tail_number": "A7-ACM",
    "icao24": "06a04e",
    "manufacturer": "Airbus",
    "model": "A330 202",
    "typecode": "A332",
    "serial_number": "849",
    "operator": "Qatar Airways",
    "built_year": 2007
  },
  {
    "tail_number": "D-AIUE",
    "icao24": "3c66a5",
    "manufacturer": "Airbus",
    "model": "A320 214SL",
    "typecode": "A320",
    "serial_number": "6092",
    "operator": "Lufthansa",
    "built_year": null
  },
  {
    "tail_number": "D-AIWD",
    "icao24": "3c66e4",
    "manufacturer": "Airbus Industrie",
    "model": "A320-214",
    "typecode": "A320",
    "serial_number": "8672",
    "operator": "Lufthansa",
    "built_year": null
  },
  {
    "tail_number": "D-AIWF",
    "icao24": "3c66e6",
    "manufacturer": "Airbus Industrie",
    "model": "A320-214",
    "typecode": "A320",
    "serial_number": "8853",
    "operator": "Lufthansa",
    "built_year": null
  },
  {
    "tail_number": "D-AIWG",
    "icao24": "3c66e7",
    "manufacturer": "Airbus Industrie",
    "model": "A320-214",
    "typecode": "A320",
    "serial_number": "8902",
    "operator": "Lufthansa",
    "built_year": null
  },
  {
    "tail_number": "D-AIWI",
    "icao24": "3c66e9",
    "manufacturer": "Airbus Industrie",
    "model": "A320-214",
    "typecode": "A320",
    "serial_number": "8951",
    "operator": "Lufthansa",
    "built_year": null
  },
  {
    "tail_number": "D-AIWK",
    "icao24": "3c66eb",
    "manufacturer": "Airbus Industrie",
    "model": "A320-214",
    "typecode": "A320",
    "serial_number": "9058",
    "operator": "Lufthansa",
    "built_year": null
  },
  {
    "tail_number": "D-AIKI",
    "icao24": "3c6569",
    "manufacturer": "Airbus",
    "model": "Airbus A330-343X",
    "typecode": "A333",
    "serial_number": "687",
    "operator": "Lufthansa",
    "built_year": null
  },
  {
    "tail_number": "D-AIKK",
    "icao24": "3c656b",
    "manufacturer": "Airbus",
    "model": "Airbus A330-343E",
    "typecode": "A333",
    "serial_number": "896",
    "operator": "Lufthansa",
    "built_year": null
  },
  {
    "tail_number": "D-AISI",
    "icao24": "3c6669",
    "manufacturer": "Airbus",
    "model": "A321 231",
    "typecode": "A321",
    "serial_number": "3339",
    "operator": "Lufthansa",
    "built_year": 2014
  },
  {
    "tail_number": "D-AIDQ",
    "icao24": "3c6491",
    "manufacturer": "Airbus",
    "model": "A321 231",
    "typecode": "A321",
    "serial_number": "5028",
    "operator": "Lufthansa",
    "built_year": null
  },
  {
    "tail_number": "D-AILB",
    "icao24": "3c6582",
    "manufacturer": "Airbus",
    "model": "A319 114",
    "typecode": "A319",
    "serial_number": "610",
    "operator": "Lufthansa",
    "built_year": 1996
  },
  {
    "tail_number": "N225NV",
    "icao24": "a1f4d4",
    "manufacturer": "Airbus Industrie",
    "model": "A320-214",
    "typecode": "A320",
    "serial_number": "706",
    "operator": "Allegiant Air",
    "built_year": 1997
  },
  {
    "tail_number": "N224NV",
    "icao24": "a1f11d",
    "manufacturer": "Airbus Industrie",
    "model": "A320-214",
    "typecode": "A320",
    "serial_number": "1694",
    "operator": "Allegiant Air",
    "built_year": null
  },
  {
    "tail_number": "N273NV",
    "icao24": "a2b2e1",
    "manufacturer": "Airbus Industrie",
    "model": "A320-214",
    "typecode": "A320",
    "serial_number": "3076",
    "operator": "Allegiant Air",
    "built_year": 2007
  },
  {
    "tail_number": "N284NV",
    "icao24": "a2de17",
    "manufacturer": "Airbus",
    "model": "A320-214",
    "typecode": "A320",
    "serial_number": "5045",
    "operator": "Allegiant Air",
    "built_year": 2012
  },
  {
    "tail_number": "N196NV",
    "icao24": "a17fb5",
    "manufacturer": "Airbus",
    "model": "A320-214",
    "typecode": "A320",
    "serial_number": "6965",
    "operator": "Allegiant Air",
    "built_year": 2016
  },
  {
    "tail_number": "N276NV",
    "icao24": "a2be06",
    "manufacturer": "Airbus",
    "model": "A320-214",
    "typecode": "A320",
    "serial_number": "8671",
    "operator": "Allegiant Air",
    "built_year": 2019
  },
  {
    "tail_number": "N942FD",
    "icao24": "ad1517",
    "manufacturer": "Boeing",
    "model": "757-225",
    "typecode": "B752",
    "serial_number": "22612",
    "operator": "FedEx Express",
    "built_year": 1986
  },
  {
    "tail_number": "N912FD",
    "icao24": "ac9e9a",
    "manufacturer": "Boeing",
    "model": "757-28A",
    "typecode": "B752",
    "serial_number": "24260",
    "operator": "FedEx Express",
    "built_year": 1988
  },
  {
    "tail_number": "N939FD",
    "icao24": "ad0799",
    "manufacturer": "Boeing",
    "model": "757-23A",
    "typecode": "B752",
    "serial_number": "24528",
    "operator": "FedEx Express",
    "built_year": null
  },
  {
    "tail_number": "N786FD",
    "icao24": "aaa751",
    "manufacturer": "Boeing",
    "model": "757-222",
    "typecode": "B752",
    "serial_number": "24995",
    "operator": "FedEx Express",
    "built_year": 1991
  },
  {
    "tail_number": "N961FD",
    "icao24": "ad605e",
    "manufacturer": "Boeing",
    "model": "757-2Y0",
    "typecode": "B752",
    "serial_number": "25268",
    "operator": "FedEx Express",
    "built_year": 1991
  },
  {
    "tail_number": "N787FD",
    "icao24": "aaab08",
    "manufacturer": "Boeing",
    "model": "757-222",
    "typecode": "B752",
    "serial_number": "26685",
    "operator": "FedEx Express",
    "built_year": 1992
  },
  {
    "tail_number": "N903FD",
    "icao24": "ac7ad2",
    "manufacturer": "Boeing",
    "model": "757-2B7",
    "typecode": "B752",
    "serial_number": "27124",
    "operator": "FedEx Express",
    "built_year": 1993
  },
  {
    "tail_number": "N956FD",
    "icao24": "ad4b72",
    "manufacturer": "Boeing",
    "model": "757-236",
    "typecode": "B752",
    "serial_number": "29115",
    "operator": "FedEx Express",
    "built_year": 1998
  }
] as const;

export const FLEET: readonly FleetAircraft[] = RAW.map((a) => ({
  ...a,
  equipment: null,
  modification: null,
}));

export const FLEET_OPERATORS: readonly string[] = ["Allegiant Air", "American Airlines", "Delta Air Lines", "FedEx Express", "Lufthansa", "Qatar Airways", "United Airlines"];

export function aircraftByTail(tail: string): FleetAircraft | undefined {
  return FLEET.find((a) => a.tail_number === tail);
}
