"""
sync_prices.py
מושך את קובצי שקיפות המחירים מכמה רשתות, מפענח אותם ומעדכן טבלאות ב-Supabase.

לא נבדק בהרצה אמיתית (הסביבה שכתבה את זה בלי גישה לאינטרנט) — יש לצפות
לכוונון קטן בהרצה הראשונה, בעיקר בשמות הפרמטרים המדויקים של הספריות.
תיעוד עדכני: https://github.com/erlichsefi/israeli-supermarket-scarpers
             https://github.com/erlichsefi/israeli-supermarket-parsers (או OpenIsraeliSupermarkets)

התקנה: pip install -r requirements.txt
הרצה:  python sync_prices.py
נדרשים משתני סביבה: SUPABASE_URL, SUPABASE_SERVICE_KEY, ENABLED_CHAINS (מופרד בפסיקים)
"""
import os
import sys
import csv
import glob
import shutil
import logging
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("sync_prices")

DUMP_DIR = "dumps"
PARSED_DIR = "parsed"
STORE_DUMP_DIR = "store_dumps"
STORE_PARSED_DIR = "store_parsed"
# שמות המפתח (ENUM) אומתו מול il_supermarket_scarper/utils/folders_name.py
# בריפו המקורי - אלה השמות המדויקים והנכונים לרשתות רמי לוי, אושר עד,
# יוחננוף וכרפור (ששילוב עם יינות ביתן תחת שם אחד בספרייה הזו).
DEFAULT_CHAINS = ["RAMI_LEVY", "OSHER_AD", "YOHANANOF", "YAYNO_BITAN_AND_CARREFOUR"]


def get_supabase():
    from supabase import create_client
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_KEY"]
    return create_client(url, key)


def download_dumps(enabled_chains):
    """מוריד את קובצי המקור הגולמיים (XML/GZ) מהרשתות שנבחרו."""
    from il_supermarket_scarper import ScarpingTask

    if os.path.isdir(DUMP_DIR):
        shutil.rmtree(DUMP_DIR)
    os.makedirs(DUMP_DIR, exist_ok=True)

    log.info("מוריד קבצים עבור: %s", enabled_chains)
    # אומת מול הקוד האמיתי של הספרייה (example.py / main.py בריפו
    # OpenIsraeliSupermarkets/israeli-supermarket-scarpers): הפרמטר לתיקיית
    # היעד הוא base_storage_path בתוך output_configuration, לא dump_folder_name.
    task = ScarpingTask(
        enabled_scrapers=enabled_chains,
        output_configuration={
            "output_mode": "disk",
            "base_storage_path": DUMP_DIR,
        },
        status_configuration={
            "database_type": "json",
            "base_path": os.path.join(DUMP_DIR, "status"),
        },
    )
    # task.start() מריץ את ההורדה ב-thread נפרד ברקע וחוזר מיד - הוא לא מחכה
    # לסיום בפועל. חובה לקרוא ל-join() כדי לחכות שההורדה באמת תסתיים
    # (אומת מול קוד המקור: scrapper_runner.py - start() מחזיר Thread, ו-join()
    # הוא זה ש"מחכה לסיום ה-thread").
    #
    # בלי limit/when_date, הספרייה מנסה להוריד את כל ההיסטוריה של קבצי
    # המחירים של כל רשת (יכול להיות אלפי קבצים) - זו הסיבה שהריצה הקודמת
    # חרגה מ-30 דקות ונעצרה. limit=1 + when_date=היום מגביל להורדת הקובץ
    # העדכני ביותר בלבד לכל סניף (אומת מול example.py הרשמי של הספרייה:
    # scraper.start(limit=1, when_date=_now())).
    task.start(limit=1, when_date=datetime.now())
    task.join()
    n_files = len(glob.glob(f"{DUMP_DIR}/**/*", recursive=True))
    log.info("סיום הורדה. קבצים בתיקייה: %d", n_files)
    if n_files == 0:
        log.warning("לא ירדו קבצים בכלל - כדאי לבדוק את שמות הרשתות ב-ENABLED_CHAINS")


def parse_dumps(enabled_chains):
    """
    הופך את הקבצים הגולמיים ל-CSV אחיד, וקורא את שורות ה-CSV בחזרה.
    אומת מול README הרשמי של il_supermarket_parsers: ConvertingTask כותב
    קבצי CSV לתיקיית פלט (לא מחזיר אובייקט פייתון ישירות), וגם כאן צריך
    start() + join() כי הריצה היא ברקע.

    בלי enabled_parsers, בריצה האמיתית ראינו בלוג שהספרייה דילגה על חלק
    מהתיקיות ("Skipping folder dumps/RamiLevy... not in requested chains")
    - כנראה יש לה רשימת ברירת מחדל משלה. מעבירים לה את אותה רשימת רשתות
    שהורדנו, כדי לוודא שהיא בפועל מפענחת את כולן.
    """
    from il_supermarket_parsers import ConvertingTask

    if os.path.isdir(PARSED_DIR):
        shutil.rmtree(PARSED_DIR)
    os.makedirs(PARSED_DIR, exist_ok=True)

    task = ConvertingTask(
        source_configuration={"folder": DUMP_DIR},
        output_configuration=[{"output_mode": "csv", "output_folder": PARSED_DIR}],
        status_configuration={"database_type": "json", "base_path": PARSED_DIR},
        enabled_parsers=enabled_chains,
    )
    task.start()
    task.join()

    csv_files = glob.glob(f"{PARSED_DIR}/**/*.csv", recursive=True)
    log.info("סיום פענוח. קבצי CSV שנוצרו: %d", len(csv_files))

    rows = []
    for path in csv_files:
        with open(path, encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)
    log.info("סה״כ שורות פריטים שנקראו: %d", len(rows))
    if rows:
        log.info("שמות העמודות שנמצאו בפועל (לצורך אבחון): %s", list(rows[0].keys()))
    return rows


def download_store_files(enabled_chains):
    """
    מוריד את קובצי "רשימת הסניפים" (STORE_FILE) בנפרד מקובצי המחירים.
    קבצים אלה מכילים את כתובת הסניף (שם, עיר, כתובת) - בלי זה אין דרך
    לחשב מרחק אמיתי לסניף, ואנחנו לא רוצים להמציא מיקומים.
    שם הפרמטר files_types ואפשרות הערך "STORE_FILE" אומתו מול הקוד המקור:
    il_supermarket_scarper/utils/file_types.py (מחלקת FileTypesFilters).
    """
    from il_supermarket_scarper import ScarpingTask

    if os.path.isdir(STORE_DUMP_DIR):
        shutil.rmtree(STORE_DUMP_DIR)
    os.makedirs(STORE_DUMP_DIR, exist_ok=True)

    log.info("מוריד קבצי רשימת סניפים עבור: %s", enabled_chains)
    task = ScarpingTask(
        enabled_scrapers=enabled_chains,
        files_types=["STORE_FILE"],
        output_configuration={
            "output_mode": "disk",
            "base_storage_path": STORE_DUMP_DIR,
        },
        status_configuration={
            "database_type": "json",
            "base_path": os.path.join(STORE_DUMP_DIR, "status"),
        },
    )
    # בלי when_date=היום: קובצי רשימת סניפים מתעדכנים הרבה פחות תכוף
    # ממחירים (לפעמים פעם בשבוע-חודש), אז הגבלה ל"היום בדיוק" גרמה לרוב
    # הרשתות לא למצוא קובץ בכלל וכתובות רבות נשארו ריקות. limit=1 לבד
    # לוקח את הקובץ העדכני ביותר הזמין, מה שקיימות ומעודכן שיהיה.
    task.start(limit=1)
    task.join()
    n_files = len(glob.glob(f"{STORE_DUMP_DIR}/**/*", recursive=True))
    log.info("סיום הורדת קבצי סניפים. קבצים בתיקייה: %d", n_files)


def parse_store_files(enabled_chains):
    """מפענח את קובצי רשימת הסניפים לשורות עם שם/כתובת/עיר לכל סניף."""
    from il_supermarket_parsers import ConvertingTask

    if os.path.isdir(STORE_PARSED_DIR):
        shutil.rmtree(STORE_PARSED_DIR)
    os.makedirs(STORE_PARSED_DIR, exist_ok=True)

    task = ConvertingTask(
        source_configuration={"folder": STORE_DUMP_DIR},
        output_configuration=[{"output_mode": "csv", "output_folder": STORE_PARSED_DIR}],
        status_configuration={"database_type": "json", "base_path": STORE_PARSED_DIR},
        enabled_parsers=enabled_chains,
    )
    task.start()
    task.join()

    csv_files = glob.glob(f"{STORE_PARSED_DIR}/**/*.csv", recursive=True)
    rows = []
    for path in csv_files:
        # תגלית מבדיקה בפועל של הלוג: בקובץ ה-CSV שממיר את קובץ הסניפים,
        # שדות ברמת "כל הקובץ" (chainid, chainname, found_folder, file_name,
        # תאריכי עדכון) מופיעים רק בשורה *הראשונה* של כל קובץ מקור - בכל
        # שאר השורות של אותו קובץ הם ריקים (בעוד ש-storeid/address/city
        # כן קיימים בכל שורה). זו הסיבה האמיתית לכך שרק 4 מתוך 321 שורות
        # "עברו" קודם - forward-fill: ממלאים כל שורה ריקה בערך האחרון
        # הלא-ריק שראינו *באותו קובץ*, כדי לא "לדלוף" קוד רשת מקובץ אחד
        # לקובץ אחר.
        last_chainid = None
        last_chainname = None
        with open(path, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                if row.get("chainid"):
                    last_chainid = row["chainid"]
                elif last_chainid:
                    row["chainid"] = last_chainid
                if row.get("chainname"):
                    last_chainname = row["chainname"]
                elif last_chainname:
                    row["chainname"] = last_chainname
                rows.append(row)
    log.info("שורות סניפים (עם כתובת) שנקראו: %d", len(rows))
    if rows:
        log.info("עמודות קובץ סניפים שנמצאו בפועל: %s", list(rows[0].keys()))
        with_chain_and_store = sum(
            1 for r in rows
            if (r.get("chainid") not in (None, "")) and (r.get("storeid") not in (None, ""))
        )
        log.info(
            "מתוך %d שורות: ל-%d יש גם chainid וגם storeid לא-ריקים (אחרי מילוי קדימה)",
            len(rows), with_chain_and_store,
        )
    return rows


def geocode(address, city):
    """
    ממיר כתובת טקסטואלית לקואורדינטות אמיתיות דרך Nominatim (OpenStreetMap) -
    שירות גיאוקוד חינמי וציבורי, בלי צורך במפתח API.
    לפי מדיניות השימוש של Nominatim: מקסימום בקשה אחת בשנייה, וצריך
    User-Agent מזהה. אם הכתובת לא נמצאת - מחזירים None ולא ממציאים מיקום.
    """
    import json as _json
    import time
    import urllib.parse
    import urllib.request

    query = ", ".join(p for p in [address, city, "ישראל"] if p)
    if not query.strip("ישראל, "):
        return None

    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode({
        "q": query, "format": "json", "limit": 1,
    })
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "smart-basket-sync/1.0 (github actions job)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = _json.loads(resp.read().decode())
    except Exception as e:
        log.warning("גיאוקוד נכשל עבור '%s': %s", query, e)
        return None
    finally:
        time.sleep(1)  # לא לחרוג ממדיניות הקצב של Nominatim

    if data:
        return float(data[0]["lat"]), float(data[0]["lon"])
    return None


def update_branches_geo(sb, store_rows):
    """
    מעדכן את טבלת branches עם כתובת אמיתית ומיקום גיאוגרפי אמיתי (geocoded),
    לסניפים שכבר נוצרו בשלב המחירים (upsert_to_supabase). בלי כתובת אמיתית
    לא מגיאוקדים ולא ממציאים - השדה location נשאר ריק.
    """

    def pick(d, *keys):
        for k in keys:
            v = d.get(k)
            if v not in (None, ""):
                return v
        return None

    chains_by_code = {}
    updated = 0
    geocoded = 0

    for row in store_rows:
        chain_code = pick(row, "chainid")
        store_code = pick(row, "storeid")
        if not chain_code or not store_code:
            continue

        if chain_code not in chains_by_code:
            # לפני התיקון כאן היה רק select - אם קוד הרשת בקובץ הסניפים לא
            # תאם *בדיוק* למחרוזת שכבר נשמרה בטבלת chains בשלב המחירים
            # (למשל כי שדה chainid חסר בקובץ מחירים מסוים ואז נופלים על שם
            # התיקייה כקוד חלופי), הסניף היה מדולג בשקט - וזה מה שקרה בפועל:
            # 321 שורות סניפים נקראו אבל רק 3 עודכנו. עכשיו עושים upsert
            # (לא רק select) כדי שכל קוד רשת אמיתי מקובץ הסניפים תמיד ימצא
            # או ייצור שורת chain תואמת, ושום סניף אמיתי לא יאבד בגלל אי-התאמה.
            chain_name = pick(row, "chainname") or f"רשת {chain_code}"
            res = sb.table("chains").upsert(
                {"name": chain_name, "chain_code": str(chain_code), "source": "store_files"},
                on_conflict="chain_code",
            ).execute()
            chains_by_code[chain_code] = res.data[0]["id"] if res.data else None
        chain_id = chains_by_code[chain_code]
        if not chain_id:
            continue

        address = pick(row, "address")
        city = pick(row, "city")
        store_name = pick(row, "storename")

        payload = {
            "chain_id": chain_id,
            "external_code": str(store_code),
            "name": store_name or f"{chain_code} {store_code}",
        }
        if address:
            payload["address"] = address
        if city:
            payload["city"] = city

        if address or city:
            geo = geocode(address, city)
            if geo:
                lat, lng = geo
                payload["location"] = f"SRID=4326;POINT({lng} {lat})"
                geocoded += 1

        sb.table("branches").upsert(payload, on_conflict="chain_id,external_code").execute()
        updated += 1

    log.info("עודכנו %d סניפים עם כתובת, מתוכם %d עם מיקום גיאוגרפי מדויק", updated, geocoded)


def upsert_to_supabase(sb, rows):
    """
    מקבל רשימה שטוחה של שורות (כל שורה = פריט אחד בסניף אחד) וכותב אותן
    לטבלאות chains / branches / products / prices.
    שמות העמודות המדויקים ב-CSV לא היו ידועים מראש - הקוד מנסה כמה שמות
    נפוצים (לפי תקן קובצי שקיפות המחירים) ומדלג על שורה עם ברקוד/מחיר חסרים.
    אם רואים בלוג "0 מחירים עודכנו" למרות שיש שורות - צריך להסתכל בלוג
    "שמות העמודות שנמצאו בפועל" ולעדכן כאן את שמות המפתחות בהתאם.
    """

    def pick(d, *keys):
        for k in keys:
            v = d.get(k)
            if v not in (None, ""):
                return v
        return None

    def chain_name_from_folder(item):
        # עמודת found_folder מכילה נתיב כמו "dumps/Yohananof/..." - השם
        # שבתיקייה קריא בהרבה משם המספר chainid, אז נשתמש בו כשם תצוגה.
        folder = pick(item, "found_folder")
        if not folder:
            return None
        parts = [p for p in str(folder).replace("\\", "/").split("/") if p and p != "dumps"]
        return parts[0] if parts else None

    now = datetime.now(timezone.utc).isoformat()
    chains_cache = {}
    branches_cache = {}
    price_rows = []
    skipped = 0

    for item in rows:
        # שמות העמודות בפועל ב-CSV שהספרייה יוצרת הם באותיות קטנות (אומת
        # מול לוג ריצה אמיתית: chainid, storeid, itemcode, itemprice וכו').
        chain_code = pick(item, "chainid")
        chain_name = chain_name_from_folder(item) or chain_code or "לא ידוע"
        if chain_code not in chains_cache:
            res = sb.table("chains").upsert(
                {"name": chain_name, "chain_code": str(chain_code or chain_name), "source": "gov_files"},
                on_conflict="chain_code",
            ).execute()
            chains_cache[chain_code] = res.data[0]["id"] if res.data else None
        chain_id = chains_cache[chain_code]

        store_code = pick(item, "storeid")
        store_key = (chain_id, store_code)
        if store_key not in branches_cache:
            res = sb.table("branches").upsert(
                {
                    "chain_id": chain_id,
                    "external_code": str(store_code),
                    "name": f"{chain_name} {store_code}",
                },
                on_conflict="chain_id,external_code",
            ).execute()
            branches_cache[store_key] = res.data[0]["id"] if res.data else None
        branch_id = branches_cache[store_key]

        barcode = pick(item, "itemcode")
        price = pick(item, "itemprice")
        if not barcode or not branch_id or price is None:
            skipped += 1
            continue

        prod = sb.table("products").upsert(
            {
                "barcode": barcode,
                "name": pick(item, "itemname") or "",
                "brand": pick(item, "manufacturername"),
                "size_label": pick(item, "quantity", "unitqty"),
                # לטבלת products יש עמודת category עם NOT NULL constraint (ראינו
                # בשגיאה: "null value in column category violates not-null
                # constraint"). עדיין אין לנו סיווג אוטומטי לפי אזור בסופר, אז
                # שמים ערך זמני - זה נושא נפרד לשיפור עתידי (שיוך אמיתי לפי קטגוריה).
                "category": "לא מסווג",
            },
            on_conflict="barcode",
        ).execute()
        product_id = prod.data[0]["id"] if prod.data else None
        if not product_id:
            skipped += 1
            continue

        price_rows.append({
            "branch_id": branch_id,
            "product_id": product_id,
            "price": price,
            "unit_price": pick(item, "unitofmeasureprice"),
            "unit_measure": pick(item, "unitofmeasure"),
            "source_updated_at": pick(item, "priceupdatetime") or now,
            "ingested_at": now,
        })

    if price_rows:
        # תגלית מריצה אמיתית: "ON CONFLICT DO UPDATE command cannot affect
        # row a second time" - כשבאותה בקשת upsert יש פעמיים אותו צירוף
        # (branch_id, product_id), פוסטגרס מסרב כי הוא לא יכול לעדכן את
        # אותה שורה פעמיים באותה פקודה. זה קורה בפועל כשאותו ברקוד מופיע
        # יותר מפעם אחת עבור אותו סניף בקובצי המקור (לדוגמה: הרשומה מופיעה
        # גם בקובץ מחירים רגיל וגם בקובץ "מלא"). פותרים בלי להמציא כלום -
        # פשוט שומרים רק את המופע האחרון שנקרא לכל צירוף (המחיר העדכני
        # ביותר שראינו), לפני השליחה בפועל.
        deduped = {}
        for row in price_rows:
            deduped[(row["branch_id"], row["product_id"])] = row
        price_rows = list(deduped.values())

        # Supabase/Postgres upsert מוגבל בכמות שורות לבקשה - שולחים ב"נגסות".
        chunk = 500
        for i in range(0, len(price_rows), chunk):
            sb.table("prices").upsert(
                price_rows[i:i + chunk], on_conflict="branch_id,product_id"
            ).execute()
    log.info("עודכנו %d מחירים. שורות שדולגו (חסר ברקוד/מחיר): %d", len(price_rows), skipped)


def main():
    enabled = os.environ.get("ENABLED_CHAINS", ",".join(DEFAULT_CHAINS)).split(",")
    sb = get_supabase()
    run = sb.table("ingestion_runs").insert({
        "source": "gov_files", "started_at": datetime.now(timezone.utc).isoformat()
    }).execute()
    run_id = run.data[0]["id"] if run.data else None
    try:
        download_dumps(enabled)
        parsed = parse_dumps(enabled)
        upsert_to_supabase(sb, parsed)

        # שלב נפרד: כתובות ומיקום אמיתי לסניפים (כדי לתמוך בחיפוש לפי רדיוס
        # בלי להמציא נתונים). רץ אחרי שלב המחירים כדי שה-chains/branches
        # הבסיסיים כבר קיימים.
        download_store_files(enabled)
        store_rows = parse_store_files(enabled)
        update_branches_geo(sb, store_rows)
        if run_id:
            sb.table("ingestion_runs").update({
                "finished_at": datetime.now(timezone.utc).isoformat()
            }).eq("id", run_id).execute()
        log.info("הריצה הסתיימה בהצלחה")
    except Exception as e:
        log.exception("הריצה נכשלה")
        if run_id:
            sb.table("ingestion_runs").update({
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "error": str(e),
            }).eq("id", run_id).execute()
        sys.exit(1)


if __name__ == "__main__":
    main()
