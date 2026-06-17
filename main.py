import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

service = os.environ.get("RENDER_SERVICE_NAME", "").lower()

if "cleaner" in service:
    from cleaner.main import main
    main()
else:
    from engine.main import auto_run, start_http, _cleaner_keep_alive
    threading.Thread(target=_cleaner_keep_alive, daemon=True).start()
    t = threading.Thread(target=start_http, daemon=True)
    t.start()
    auto_run()
