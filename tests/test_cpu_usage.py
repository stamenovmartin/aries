"""CPU answers must use sampled execution time, not load average."""
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests._bootstrap import bootstrap, check, run_module
bootstrap('aries-cpu-usage')
from aries.health import probes


async def test_cpu_sample():
    # 20 work ticks, 60 idle ticks and 20 iowait ticks = 20% execution.
    with patch.object(probes, '_read', side_effect=[
        'cpu 100 0 100 800 100 0 0 0 50 0',
        'cpu 120 0 100 860 120 0 0 0 70 0']), \
         patch.object(probes.asyncio, 'sleep', new_callable=AsyncMock) as pause:
        reading = await probes._cpu_usage()
    check('CPU execution excludes idle/iowait and does not double count guests',
          reading.value == 20.0 and reading.metric == 'cpu.used_pct')
    check('sampling yields to other tasks instead of blocking', pause.await_count == 1)


async def test_unavailable_samples():
    for label, samples in [
        ('missing counters', [None]),
        ('malformed counters', ['cpu nope']),
        ('unchanged counters', ['cpu 1 0 1 8 0 0 0 0'] * 2),
        ('regressing counters', ['cpu 2 0 1 8 0 0 0 0', 'cpu 1 0 1 8 0 0 0 0'])]:
        with patch.object(probes, '_read', side_effect=samples), \
             patch.object(probes.asyncio, 'sleep', new_callable=AsyncMock):
            reading = await probes._cpu_usage()
        check(label + ' never reports zero usage', reading.value is None and bool(reading.unavailable))


async def test_real_cpu_probe():
    result = await probes.probe_cpu()
    readings = {r.metric: r for r in result.readings}
    check('live probe supplies the metric required by the CPU answer contract',
          0 <= readings['cpu.used_pct'].value <= 100)
    check('load and pressure remain separate measurements',
          {'cpu.load_per_core', 'cpu.pressure'} <= readings.keys())


if __name__ == '__main__':
    sys.exit(run_module(sys.modules[__name__]))
