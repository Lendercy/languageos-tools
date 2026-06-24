from languageos_tools.datastore.activity import init_activity_tracking


def main() -> None:
    print("Init Activity Tracking")
    print("=" * 60)

    result = init_activity_tracking()

    print(f"[OK] DB path: {result['db_path']}")
    print("[OK] Activity tracking schema initialized.")


if __name__ == "__main__":
    main()