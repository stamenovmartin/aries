"""Read-only Settings first-content-paint benchmark; closes only its own windows."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from aries_ui.client import Client
from aries_ui.pages.settings import SettingsPage
from gi.repository import Gtk, Adw, GLib


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--power-delay', type=float, default=0)
    parser.add_argument('--samples', type=int, default=3)
    args = parser.parse_args()
    Gtk.init()
    Adw.init()
    samples = []
    for index in range(args.samples):
        requests = []

        class ReadOnlyClient(Client):
            def request(self, method, path, **kwargs):
                assert method == 'GET', 'Benchmark forbids writes'
                start = time.perf_counter()
                if path == '/api/aries/power':
                    time.sleep(args.power_delay)
                result = super().request(method, path, **kwargs)
                requests.append({'path': path, 'seconds': time.perf_counter() - start})
                return result

        loop = GLib.MainLoop()
        page = SettingsPage(SimpleNamespace(client=ReadOnlyClient()))
        window = Gtk.Window(title='ARIES owned Settings timing probe', default_width=940, default_height=820)
        window.set_child(page)
        start = time.perf_counter()
        sample = {'sample': index, 'first_content_paint_s': None}

        def painted(clock):
            if page._loaded_once:
                sample['first_content_paint_s'] = time.perf_counter() - start
                sample['controls'] = len(getattr(page, '_visible_settings', []))
                loop.quit()

        window.present()
        clock = window.get_frame_clock()
        signal = clock.connect('after-paint', painted)
        page.reload()
        timer = GLib.timeout_add_seconds(15, lambda: (loop.quit(), False)[1])
        loop.run()
        GLib.source_remove(timer)
        clock.disconnect(signal)
        window.destroy()
        sample['requests_completed_at_first_paint'] = list(requests)
        samples.append(sample)
        print(json.dumps(sample), flush=True)
    report = {'recorded_at': datetime.now(timezone.utc).isoformat(), 'n': len(samples),
              'power_delay_injected_s': args.power_delay, 'surface': 'live API and mapped owned GTK window',
              'production_settings_written': False, 'samples': samples}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    return int(any(row['first_content_paint_s'] is None or not row.get('controls') for row in samples))


if __name__ == '__main__':
    raise SystemExit(main())
