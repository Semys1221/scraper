import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

service = os.environ.get("RENDER_SERVICE_NAME", "").lower()

if "cleaner" in service:
    from cleaner.main import main
    main()
else:
    from engine.main import start_http, _cleaner_keep_alive
    from engine.scraper import start_auto_discover
    threading.Thread(target=_cleaner_keep_alive, daemon=True).start()
    start_auto_discover()
    t = threading.Thread(target=start_http, daemon=True)
    t.start()
    while True:
        time.sleep(60)
