# Copyright 2026 stevej52
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Measure how loaded this machine is: CPU, GPU and memory.

On a Jetson the numbers come from ``tegrastats``, which knows the GPU. On
any other Linux machine they come from ``/proc``, which does not, so the GPU
reads "-" there. Nothing here needs ROS, CUDA or root, so
``python3 -m gpu_tools.load`` runs anywhere; the ``load_monitor`` node
publishes the same numbers on ``/diagnostics``.

This is the ruler for the roadmap's "measure first" step: run it next to the
full robot launch and see what is actually busy before accelerating anything.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import os
import re
import shutil
import subprocess
import sys
import threading
import time


@dataclass
class LoadSample:
    """One reading of the machine's load."""

    source: str                                   # 'tegrastats' or 'proc'
    cpu_percent: float | None = None              # average over the cores that are on
    cpu_cores: list[float | None] = field(default_factory=list)   # None: core is off
    gpu_percent: float | None = None              # None: nothing here can see the GPU
    gpu_freq_mhz: float | None = None
    mem_used_mb: float | None = None
    mem_total_mb: float | None = None
    swap_used_mb: float | None = None
    swap_total_mb: float | None = None
    cpu_temp_c: float | None = None
    gpu_temp_c: float | None = None
    power_mw: float | None = None
    raw: str = ''                                 # the tegrastats line, for debugging

    @property
    def mem_percent(self) -> float | None:
        """Memory in use as a percentage of the total."""
        if not self.mem_total_mb or self.mem_used_mb is None:
            return None
        return 100.0 * self.mem_used_mb / self.mem_total_mb

    def key_values(self) -> list[tuple[str, str]]:
        """Return the sample as (key, value) strings, for ``/diagnostics``."""
        def fmt(value: float | None, digits: int = 0) -> str:
            return '-' if value is None else f'{value:.{digits}f}'

        cores = ','.join('off' if core is None else f'{core:.0f}' for core in self.cpu_cores)
        return [
            ('source', self.source),
            ('cpu_percent', fmt(self.cpu_percent)),
            ('cpu_cores_percent', cores or '-'),
            ('gpu_percent', fmt(self.gpu_percent)),
            ('gpu_freq_mhz', fmt(self.gpu_freq_mhz)),
            ('mem_used_mb', fmt(self.mem_used_mb)),
            ('mem_total_mb', fmt(self.mem_total_mb)),
            ('mem_percent', fmt(self.mem_percent)),
            ('swap_used_mb', fmt(self.swap_used_mb)),
            ('swap_total_mb', fmt(self.swap_total_mb)),
            ('cpu_temp_c', fmt(self.cpu_temp_c, 1)),
            ('gpu_temp_c', fmt(self.gpu_temp_c, 1)),
            ('power_mw', fmt(self.power_mw)),
        ]

    def summary(self) -> str:
        """One line, the way ``load_sample`` prints it."""
        def pct(value: float | None) -> str:
            return '-' if value is None else f'{value:.0f}%'

        parts = [f'cpu {pct(self.cpu_percent)}', f'gpu {pct(self.gpu_percent)}']
        if self.mem_total_mb:
            parts.append(f'mem {self.mem_used_mb:.0f}/{self.mem_total_mb:.0f}MB'
                         f' ({pct(self.mem_percent)})')
        if self.swap_total_mb:
            parts.append(f'swap {self.swap_used_mb:.0f}/{self.swap_total_mb:.0f}MB')
        if self.gpu_temp_c is not None:
            parts.append(f'gpu {self.gpu_temp_c:.0f}C')
        if self.cpu_temp_c is not None:
            parts.append(f'cpu {self.cpu_temp_c:.0f}C')
        if self.power_mw is not None:
            parts.append(f'{self.power_mw / 1000:.1f}W')
        return '  '.join(parts)


# tegrastats prints one line per interval. JetPack 5 wrote "GR3D_FREQ 0%" and
# a separate GR3D2 entry; JetPack 6 and 7 write "GR3D_FREQ 0%@[306]" (one
# frequency per GPU cluster). Cores that are switched off show as "off".
_RAM = re.compile(r'\bRAM (\d+)/(\d+)MB')
_SWAP = re.compile(r'\bSWAP (\d+)/(\d+)MB')
_CPU = re.compile(r'\bCPU \[([^\]]*)\]')
_GR3D = re.compile(r'\bGR3D_FREQ (\d+)%(?:@\[?([\d,]+)\]?)?')
_TEMP = re.compile(r'\b(cpu|gpu)@([\d.]+)C')
_POWER = re.compile(r'\bVDD_IN (\d+)mW')


def parse_tegrastats(line: str) -> LoadSample:
    """Turn one tegrastats line into a sample; fields it lacks stay None."""
    sample = LoadSample(source='tegrastats', raw=line.strip())
    if match := _RAM.search(line):
        sample.mem_used_mb, sample.mem_total_mb = float(match[1]), float(match[2])
    if match := _SWAP.search(line):
        sample.swap_used_mb, sample.swap_total_mb = float(match[1]), float(match[2])
    if match := _CPU.search(line):
        for entry in match[1].split(','):
            entry = entry.strip()
            if not entry or entry == 'off':
                sample.cpu_cores.append(None)
            else:
                sample.cpu_cores.append(float(entry.split('%')[0]))
        on = [core for core in sample.cpu_cores if core is not None]
        sample.cpu_percent = sum(on) / len(on) if on else None
    if match := _GR3D.search(line):
        sample.gpu_percent = float(match[1])
        if match[2]:
            sample.gpu_freq_mhz = float(match[2].split(',')[0])
    for name, value in _TEMP.findall(line):
        if name == 'cpu':
            sample.cpu_temp_c = float(value)
        else:
            sample.gpu_temp_c = float(value)
    if match := _POWER.search(line):
        sample.power_mw = float(match[1])
    return sample


class ProcSampler:
    """Load from ``/proc`` on any Linux machine. Knows nothing about the GPU."""

    def __init__(self, root: str = '/') -> None:
        """Take the first CPU reading; the first ``sample()`` measures from here."""
        self._stat = os.path.join(root, 'proc', 'stat')
        self._meminfo = os.path.join(root, 'proc', 'meminfo')
        self._last = self._read_stat()

    def _read_stat(self) -> dict[str, tuple[int, int]]:
        """Return (busy, total) jiffies per CPU line ('cpu' is the sum of all cores)."""
        counters: dict[str, tuple[int, int]] = {}
        with open(self._stat) as stat:
            for line in stat:
                if not line.startswith('cpu'):
                    continue
                name, *values = line.split()
                jiffies = [int(value) for value in values[:8]]
                total = sum(jiffies)
                idle = sum(jiffies[3:5])           # idle + iowait
                counters[name] = (total - idle, total)
        return counters

    def _read_meminfo(self) -> dict[str, float]:
        """Return the /proc/meminfo values in MB."""
        values: dict[str, float] = {}
        with open(self._meminfo) as meminfo:
            for line in meminfo:
                key, _, rest = line.partition(':')
                number = rest.split()
                if number:
                    values[key] = float(number[0]) / 1024.0
        return values

    def sample(self) -> LoadSample:
        """Measure the load since the previous call (or since construction)."""
        current = self._read_stat()
        sample = LoadSample(source='proc')

        def percent(name: str) -> float | None:
            if name not in current or name not in self._last:
                return None
            busy = current[name][0] - self._last[name][0]
            total = current[name][1] - self._last[name][1]
            return 100.0 * busy / total if total > 0 else None

        sample.cpu_percent = percent('cpu')
        cores = sorted((name for name in current if name != 'cpu'), key=lambda n: int(n[3:]))
        sample.cpu_cores = [percent(name) for name in cores]
        self._last = current

        memory = self._read_meminfo()
        if 'MemTotal' in memory:
            sample.mem_total_mb = memory['MemTotal']
            available = memory.get('MemAvailable', memory.get('MemFree', 0.0))
            sample.mem_used_mb = memory['MemTotal'] - available
        if 'SwapTotal' in memory:
            sample.swap_total_mb = memory['SwapTotal']
            sample.swap_used_mb = memory['SwapTotal'] - memory.get('SwapFree', 0.0)
        return sample

    def close(self) -> None:
        """Nothing to release."""


class TegrastatsSampler:
    """Load from ``tegrastats``, kept running in the background on a Jetson."""

    def __init__(self, interval_ms: int = 1000, command: str = 'tegrastats') -> None:
        """Start tegrastats; readings arrive after its first interval."""
        self._process = subprocess.Popen(
            [command, '--interval', str(interval_ms)],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        self._latest: LoadSample | None = None
        self._lock = threading.Lock()
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()

    @staticmethod
    def available() -> bool:
        """Return True when this machine has tegrastats (any Jetson)."""
        return shutil.which('tegrastats') is not None

    def _read(self) -> None:
        assert self._process.stdout is not None
        for line in self._process.stdout:
            if line.strip():
                with self._lock:
                    self._latest = parse_tegrastats(line)

    def sample(self) -> LoadSample | None:
        """Return the most recent tegrastats line, or None before the first one."""
        with self._lock:
            return self._latest

    def close(self) -> None:
        """Stop tegrastats."""
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._process.kill()


def make_sampler(source: str = 'auto', interval_ms: int = 1000):
    """Pick tegrastats on a Jetson and /proc anywhere else, or force one with ``source``."""
    if source == 'tegrastats' or (source == 'auto' and TegrastatsSampler.available()):
        return TegrastatsSampler(interval_ms=interval_ms)
    if source in ('auto', 'proc'):
        return ProcSampler()
    raise ValueError(f'unknown source {source!r}; use auto, tegrastats or proc')


def main(argv: list[str] | None = None) -> int:
    """Print one load line per interval, then the average. Entry point of ``load_sample``."""
    parser = argparse.ArgumentParser(
        prog='load_sample', description='Print how loaded this machine is.')
    parser.add_argument('--samples', type=int, default=1,
                        help='how many lines to print (default 1)')
    parser.add_argument('--interval', type=float, default=1.0,
                        help='seconds between lines (default 1.0)')
    parser.add_argument('--source', choices=['auto', 'tegrastats', 'proc'], default='auto',
                        help='where to read from (default: tegrastats on a Jetson, else /proc)')
    args = parser.parse_args(argv)

    sampler = make_sampler(args.source, interval_ms=max(1, int(args.interval * 1000)))
    taken: list[LoadSample] = []
    try:
        for index in range(args.samples):
            time.sleep(args.interval)
            sample = sampler.sample()
            if sample is None:      # tegrastats has not printed yet
                continue
            taken.append(sample)
            print(f'{(index + 1) * args.interval:6.1f}s  {sample.summary()}')
    except KeyboardInterrupt:
        pass
    finally:
        sampler.close()
    if len(taken) > 1:
        print(f'average of {len(taken)}:  {average(taken).summary()}')
    return 0 if taken else 1


def average(samples: list[LoadSample]) -> LoadSample:
    """Average the numeric fields of several samples (memory: the maximum)."""
    def mean(values: list[float | None]) -> float | None:
        known = [value for value in values if value is not None]
        return sum(known) / len(known) if known else None

    def maximum(values: list[float | None]) -> float | None:
        known = [value for value in values if value is not None]
        return max(known) if known else None

    return LoadSample(
        source=samples[0].source,
        cpu_percent=mean([s.cpu_percent for s in samples]),
        gpu_percent=mean([s.gpu_percent for s in samples]),
        gpu_freq_mhz=mean([s.gpu_freq_mhz for s in samples]),
        mem_used_mb=maximum([s.mem_used_mb for s in samples]),
        mem_total_mb=samples[0].mem_total_mb,
        swap_used_mb=maximum([s.swap_used_mb for s in samples]),
        swap_total_mb=samples[0].swap_total_mb,
        cpu_temp_c=maximum([s.cpu_temp_c for s in samples]),
        gpu_temp_c=maximum([s.gpu_temp_c for s in samples]),
        power_mw=mean([s.power_mw for s in samples]),
    )


if __name__ == '__main__':
    sys.exit(main())
