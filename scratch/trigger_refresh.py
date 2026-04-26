import asyncio
from app.database import SessionLocal
from app.maintenance import refresh_poor_metadata

def run_refresh():
    db = SessionLocal()
    try:
        print("Starting metadata refresh for poor records...")
        result = refresh_poor_metadata(db)
        print(f"Refresh complete: {result}")
    finally:
        db.close()

if __name__ == "__main__":
    run_refresh()
