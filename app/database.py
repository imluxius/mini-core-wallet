import struct
from datetime import datetime, timezone, timedelta
import pyodbc

def get_sql_server_driver() -> str:
    drivers = [d for d in pyodbc.drivers() if "SQL Server" in d]
    for preferred in ["ODBC Driver 18 for SQL Server", "ODBC Driver 17 for SQL Server"]:
        if preferred in drivers:
            return preferred
    if drivers:
        return drivers[-1]
    raise RuntimeError("Không tìm thấy ODBC Driver cho SQL Server trên máy!")

DRIVER_NAME = get_sql_server_driver()

CONN_STR = (
    f"DRIVER={{{DRIVER_NAME}}};"
    "SERVER=localhost,1433;"
    "DATABASE=core_wallet_db;"
    "UID=sa;"
    "PWD=FintechPassword@123;"
    "TrustServerCertificate=yes;"
)

# Bộ giải mã kiểu DATETIMEOFFSET (SQL type -155) của SQL Server sang datetime của Python
def handle_datetimeoffset(dto_value):
    tup = struct.unpack("<hHHHHHIhh", dto_value)
    return datetime(
        tup[0], tup[1], tup[2], tup[3], tup[4], tup[5],
        tup[6] // 1000,
        timezone(timedelta(hours=tup[7], minutes=tup[8]))
    )

def get_db_connection():
    conn = pyodbc.connect(CONN_STR, autocommit=False)
    conn.add_output_converter(-155, handle_datetimeoffset)
    return conn