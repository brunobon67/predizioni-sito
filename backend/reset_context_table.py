from app import engine, Base, MatchContext

def main():
    print("🧹 Dropping table: match_context ...")
    MatchContext.__table__.drop(bind=engine, checkfirst=True)
    print("✅ Dropped (if existed).")

    print("🛠️ Creating table: match_context ...")
    MatchContext.__table__.create(bind=engine, checkfirst=True)
    print("✅ Created.")

if __name__ == "__main__":
    main()
