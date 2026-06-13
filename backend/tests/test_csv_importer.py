"""Stage 6E pre-flight — CSV importer parser tests.
Covers the five real-world platform formats and the Fix-8 tolerance rules.
"""
import os
import sys
sys.path.insert(0, "/app/backend")

import csv_importer


def test_decode_utf8_with_bom():
    assert csv_importer.decode_csv_bytes("\ufeffhello".encode("utf-8")).startswith("hello")


def test_decode_latin1_fallback():
    # 0xe0 is "à" in Latin-1, invalid in UTF-8.
    raw = "Andr\xe0,Paris".encode("latin-1")
    out = csv_importer.decode_csv_bytes(raw)
    assert "Andrà" in out


def test_detect_tokeet_bom():
    text = "\ufeffRENTAL NAME,GUEST NAME,Booked Date,NIGHTS,Arrive,Depart,Source,TAX,FEE,DISCOUNTS,TOTAL\n"
    det = csv_importer.detect_platform(text)
    assert det["platform"] == "Tokeet"
    assert det["mode"] == "booking_import"


def test_detect_vikbooking():
    text = "Booking ID,Source,Source type,Reference,Status,Created at,Checkin date,Checkout date,Rooms,Room types,Primary guest first name,Primary guest last name,Country,Adults,Children,Accommodation,Total,Cancelled at\n"
    det = csv_importer.detect_platform(text)
    assert det["platform"] == "VikBooking"


def test_detect_preno():
    text = (
        ",,,,,Guest Booking Details,,,,,,,,,,,\n"
        ",,,,,\"Tuesday, May 05 2026 1:42 PM\",,,,,,,,,,,\n"
        "Last Name,First Name,Title,Email,Company,,State,City,Country,,Phone,Check-in,,Depart,Nights,Room #,Type\n"
    )
    det = csv_importer.detect_platform(text)
    assert det["platform"] == "Preno"
    assert det["skip_rows"] == 2


def test_detect_guestpoint_person_detail():
    text = (
        ",,Person Detail Report,,,,,,,,,\n"
        ",,\"Monday, June 08 2026 3:31 PM\",,,,,,,,,,\n"
        ",,,,,,,,,Last 12 Months,,\n"
        "Name,Address,City,State,Postcode,Country,First Stay,Last Stay,Nights Stayed,Total Spend\n"
    )
    det = csv_importer.detect_platform(text)
    assert det["platform"] == "Guestpoint Person Detail"
    assert det["mode"] == "profile_enrichment"
    assert det["skip_rows"] == 3


def test_detect_guestpoint_customer_export():
    text = "ID,Last Name,First Name,eMail,Phone,Address,City,ZIP,Country,Gender,Date of Birth,Total Bookings,Notes\n"
    det = csv_importer.detect_platform(text)
    assert det["platform"] == "Guestpoint Customer Export"
    assert det["mode"] == "profile_enrichment"


def _parse(text: str, name: str = "test.csv") -> dict:
    return csv_importer.parse_upload(text.encode("utf-8"), name)


def test_tokeet_full_flow():
    text = (
        "\ufeffRENTAL NAME,GUEST NAME,Booked Date,NIGHTS,Arrive,Depart,Source,TAX,FEE,DISCOUNTS,TOTAL\n"
        "Spa Apartment Unit 28,\"Jane Doe\",\"10 May, 2026\",3,\"15 May, 2026\",\"18 May, 2026\",Airbnb,30,15,0,\"A$540.00\"\n"
        "Spa Apartment Unit 29,\"John Smith Jr\",\"01 Apr, 2026\",5,\"05 Apr, 2026\",\"10 Apr, 2026\",Direct,0,0,0,\"A$900\"\n"
    )
    out = _parse(text)
    assert out["platform"] == "Tokeet"
    assert out["mode"] == "booking_import"
    assert out["valid_rows"] == 2
    r = out["rows"][0]
    assert r["reservation_id"].startswith("TOK-")
    assert r["guest_first_name"] == "Jane" and r["guest_last_name"] == "Doe"
    assert r["checkin_date"] == "2026-05-15"
    assert r["checkout_date"] == "2026-05-18"
    assert r["booking_date"] == "2026-05-10"
    assert r["booking_value"] == 540.0
    assert r["guest_email"] is None
    assert r["is_cancelled"] is False
    assert out["rows"][1]["guest_last_name"] == "Smith Jr"


def test_vikbooking_full_flow():
    text = (
        "Booking ID,Source,Source type,Reference,Status,Created at,Checkin date,Checkout date,Rooms,Room types,Primary guest first name,Primary guest last name,Country,Adults,Children,Accommodation,Total,Cancelled at\n"
        "VIK001,Booking.com,OTA,REF1,Confirmed,22/04/2026 14:32,01/05/2026,05/05/2026,Beach Villa,Villa,Alice,Brown,AU,2,1,400.00,520.50,\n"
        "VIK002,Direct,Direct,REF2,Cancelled,15/03/2026 09:00,10/04/2026,12/04/2026,Loft 12,Apartment,Bob,Green,AU,1,0,150.00,200.00,16/03/2026 10:00\n"
    )
    out = _parse(text)
    assert out["platform"] == "VikBooking"
    assert out["valid_rows"] == 2
    r0 = out["rows"][0]
    assert r0["reservation_id"] == "VIK001"
    assert r0["checkin_date"] == "2026-05-01"
    assert r0["checkout_date"] == "2026-05-05"
    assert r0["booking_date"] == "2026-04-22"
    assert r0["guest_count"] == 3
    assert r0["booking_value"] == 520.50
    assert r0["is_cancelled"] is False
    assert out["rows"][1]["is_cancelled"] is True  # Status=Cancelled OR cancelled_at non-empty


def test_preno_full_flow():
    text = (
        ",,,,,Guest Booking Details,,,,,,,,,,,\n"
        ",,,,,\"Tuesday, May 05 2026 1:42 PM\",,,,,,,,,,,\n"
        "Last Name,First Name,Title,Email,Company,Col6,State,City,Country,Col10,Phone,Check-in,Col13,Depart,Nights,Room #,Type\n"
        "Smith,Jane,Ms,jane@guest.booking.com,,,,Sydney,AU,,+61400000000,15/05/2026,,18/05/2026,3,A12,Studio\n"
        "Brown,Peter,Mr,peter@example.com,,,,Melbourne,AU,,+61400000001,01/06/2026,,05/06/2026,4,B7,Suite\n"
    )
    out = _parse(text)
    assert out["platform"] == "Preno"
    assert out["valid_rows"] == 2
    r0 = out["rows"][0]
    assert r0["reservation_id"].startswith("PRE-")
    assert "SMITH" in r0["reservation_id"]
    assert r0["guest_email"] == "jane@guest.booking.com"
    assert r0["raw_booking_source"] == "Booking.com"  # routed via email rule
    assert r0["checkin_date"] == "2026-05-15"
    assert r0["booking_value"] is None
    assert r0["is_cancelled"] is False
    assert out["rows"][1]["raw_booking_source"] == "Direct"
    assert out["rows"][1]["property_name"] == "Suite"


def test_guestpoint_person_detail_flow():
    text = (
        ",,Person Detail Report,,,,,,,,,\n"
        ",,\"Monday, June 08 2026 3:31 PM\",,,,,,,,,,\n"
        ",,,,,,,,,Last 12 Months,,\n"
        "Name,Address,City,State,Postcode,Country,First Stay,Last Stay,Nights Stayed,Total Spend\n"
        "Jane  Doe,12 Bay Rd,Sydney,NSW,2000,AU,01/01/2026,01/05/2026,12,\"AU $4,500.00\"\n"
        "Peter Brown,9 Hill St,Melbourne,VIC,3000,AU,15/02/2026,15/04/2026,8,\"AU $2,300\"\n"
    )
    out = _parse(text)
    assert out["platform"] == "Guestpoint Person Detail"
    assert out["mode"] == "profile_enrichment"
    assert out["valid_rows"] == 2
    r = out["rows"][0]
    # Name "Jane  Doe" with double-space must be normalised then split.
    assert r["guest_first_name"] == "Jane" and r["guest_last_name"] == "Doe"
    assert r["lifetime_spend_reported"] == 4500.0
    assert r["nights_stayed"] == 12
    assert r["guest_email"] is None
    # DD/MM/YYYY must be honoured — "01/05/2026" is 1 May 2026.
    assert r["first_stay"] == "2026-01-01"
    assert r["last_stay"] == "2026-05-01"
    # No reservation fields present.
    assert "reservation_id" not in r


def test_guestpoint_customer_export_flow_latin1():
    # Force Latin-1 — 0xe0 = "à"
    raw_text = (
        "ID,Last Name,First Name,eMail,Phone,Address,City,ZIP,Country,Gender,Date of Birth,Total Bookings,Notes\n"
        "1,Andr\xe0,Marie,marie@example.com,+61400,1 St,Sydney,2000,AU,F,01/01/1990,3,VIP\n"
    ).encode("latin-1")
    out = csv_importer.parse_upload(raw_text, "x.csv")
    assert out["platform"] == "Guestpoint Customer Export"
    assert out["mode"] == "profile_enrichment"
    assert out["valid_rows"] == 1
    r = out["rows"][0]
    assert r["guest_first_name"] == "Marie"
    assert r["guest_last_name"] == "Andrà"  # Latin-1 decoded successfully
    assert r["guest_email"] == "marie@example.com"
    assert r["total_bookings_reported"] == 3
    assert r["date_of_birth"] == "1990-01-01"


def test_keep_row_tolerance_rules():
    # Booking row: only skip when BOTH name and checkin missing.
    r1 = {"guest_first_name": "", "guest_last_name": "", "checkin_date": None}
    r2 = {"guest_first_name": "John", "guest_last_name": "", "checkin_date": None}
    r3 = {"guest_first_name": "", "guest_last_name": "", "checkin_date": "2026-01-01"}
    assert csv_importer.keep_row(r1) is False
    assert csv_importer.keep_row(r2) is True
    assert csv_importer.keep_row(r3) is True


def test_money_parsing():
    assert csv_importer.parse_money("A$540.00") == 540.0
    assert csv_importer.parse_money("AU $4,500.00") == 4500.0
    assert csv_importer.parse_money("$1,234.56") == 1234.56
    assert csv_importer.parse_money(None) is None
    assert csv_importer.parse_money("") is None


def test_generic_still_works():
    text = (
        "reservation_id,first_name,last_name,email,property,checkin,checkout,total,source\n"
        "R1,Jane,Doe,j@x.com,Loft,2026-06-01,2026-06-04,300,Airbnb\n"
    )
    out = _parse(text)
    assert out["platform"] == "Generic"
    assert out["valid_rows"] == 1
    r = out["rows"][0]
    assert r["reservation_id"] == "R1"
    assert r["guest_first_name"] == "Jane"
    assert r["booking_value"] == 300.0
