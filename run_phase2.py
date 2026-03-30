"""Wrapper to run test_pipeline_phase2 with output captured to file."""
import sys
import os
import traceback

_dir = os.path.dirname(os.path.abspath(sys.argv[0] if sys.argv[0] else __file__))
os.chdir(_dir)
sys.path.insert(0, _dir)

log_path = os.path.join(_dir, "uds_gen_output2.log")
log_f = open(log_path, "w", encoding="utf-8")

class Tee:
    def __init__(self, *streams):
        self.streams = streams
    def write(self, data):
        for s in self.streams:
            try:
                s.write(data)
                s.flush()
            except Exception:
                pass
    def flush(self):
        for s in self.streams:
            try:
                s.flush()
            except Exception:
                pass

sys.stdout = Tee(sys.__stdout__, log_f)
sys.stderr = Tee(sys.__stderr__, log_f)

try:
    from test_pipeline_phase2 import main
    main()
except Exception as e:
    print(f"\n\nFATAL ERROR: {e}\n{traceback.format_exc()}", flush=True)
finally:
    log_f.close()
