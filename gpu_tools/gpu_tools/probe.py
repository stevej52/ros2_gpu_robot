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
Find out what GPU acceleration is available on this machine.

Works on any Linux computer. On a Jetson it also reports the module, the
Jetson Linux and JetPack versions. It looks for the CUDA toolkit and for the
Python libraries that can use the GPU (PyTorch, CuPy, TensorRT) and says,
for each, whether it is installed and whether it can actually see a GPU.

Nothing here needs ROS, so ``python3 -m gpu_tools.probe`` runs before ROS 2
is installed and inside any virtual environment.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass, field
import importlib
import os
import platform
import re
import shutil
import socket
import subprocess
import sys

ImportModule = Callable[[str], object]


@dataclass
class LibraryStatus:
    """What one Python GPU library reports about itself."""

    name: str
    version: str | None = None   # None: not installed
    device: str | None = None    # the GPU's name when the library can see one
    detail: str | None = None    # why there is no GPU, or extra information

    @property
    def installed(self) -> bool:
        """True when the library could be imported."""
        return self.version is not None

    @property
    def has_gpu(self) -> bool:
        """True when the library reports a usable GPU."""
        return self.device is not None

    def describe(self) -> str:
        """One line for a report."""
        if not self.installed:
            return f'{self.name}: not installed'
        if self.has_gpu:
            return f'{self.name} {self.version}: {self.device}'
        return f'{self.name} {self.version}: no GPU ({self.detail or "not available"})'


@dataclass
class GpuReport:
    """Everything ``probe()`` found out."""

    hostname: str
    machine: str
    os_name: str
    kernel: str
    python: str
    jetson_model: str | None = None
    jetson_linux: str | None = None
    jetpack: str | None = None
    cuda_toolkit: str | None = None
    nvcc: str | None = None
    libraries: list[LibraryStatus] = field(default_factory=list)

    @property
    def is_jetson(self) -> bool:
        """True on any NVIDIA Jetson."""
        return self.jetson_linux is not None or self.jetson_model is not None

    @property
    def gpu_available(self) -> bool:
        """True when at least one Python library can use a GPU."""
        return any(lib.has_gpu for lib in self.libraries)

    def lines(self) -> list[str]:
        """Return the report lines as ``gpu_info`` prints them."""
        def row(label: str, value: str | None) -> str:
            return f'{label + ":":14}{value if value is not None else "-"}'

        out = [
            row('host', self.hostname),
            row('machine', self.machine),
            row('os', self.os_name),
            row('kernel', self.kernel),
            row('python', self.python),
        ]
        if self.is_jetson:
            out += [
                row('jetson', self.jetson_model or 'yes'),
                row('jetson linux', self.jetson_linux),
                row('jetpack', self.jetpack or 'nvidia-jetpack not installed'),
            ]
        if self.cuda_toolkit:
            out.append(row('cuda toolkit', f'{self.cuda_toolkit} ({self.nvcc})'))
        else:
            out.append(row('cuda toolkit', 'not found'))
        out += [lib.describe() for lib in self.libraries]
        out.append(row('gpu', 'yes' if self.gpu_available else 'no'))
        return out

    def summary(self) -> str:
        """Return one line: which machine, and what GPU access it has."""
        seen = [f'{lib.name} on {lib.device}' for lib in self.libraries if lib.has_gpu]
        where = self.jetson_model or self.hostname
        if seen:
            return f'{where}: GPU available via {", ".join(seen)}'
        return f'{where}: no Python library can see a GPU'


# --- helpers ----------------------------------------------------------------

def read_first_line(path: str) -> str | None:
    """Return the first line of a text file, or None if it cannot be read."""
    try:
        with open(path, encoding='utf-8', errors='replace') as handle:
            return handle.readline().strip('\n\r\x00 ')
    except OSError:
        return None


def run(cmd: list[str]) -> str | None:
    """Run a command and return its stdout, or None if it fails or is missing."""
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=15, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def parse_jetson_linux(text: str | None) -> str | None:
    """Turn the first line of /etc/nv_tegra_release into '39.2.1'."""
    if not text:
        return None
    match = re.search(r'R(\d+)\s*\(release\),\s*REVISION:\s*([\d.]+)', text)
    return f'{match.group(1)}.{match.group(2)}' if match else None


def parse_nvcc_version(text: str | None) -> str | None:
    """Turn ``nvcc --version`` output into '13.2'."""
    if not text:
        return None
    match = re.search(r'release\s+([\d.]+)', text)
    return match.group(1) if match else None


def parse_os_release(path: str) -> str | None:
    """Return PRETTY_NAME from an os-release file."""
    try:
        with open(path, encoding='utf-8') as handle:
            for line in handle:
                if line.startswith('PRETTY_NAME='):
                    return line.split('=', 1)[1].strip().strip('"')
    except OSError:
        pass
    return None


def find_nvcc(root: str = '/') -> str | None:
    """Locate nvcc on PATH or in the JetPack default location."""
    found = shutil.which('nvcc')
    if found:
        return found
    candidate = os.path.join(root, 'usr', 'local', 'cuda', 'bin', 'nvcc')
    return candidate if os.access(candidate, os.X_OK) else None


# --- library probes ---------------------------------------------------------

def probe_torch(import_module: ImportModule = importlib.import_module) -> LibraryStatus:
    """Check PyTorch: is it installed, and can it see a CUDA device."""
    status = LibraryStatus('torch')
    try:
        torch = import_module('torch')
    except Exception as error:  # noqa: B902  # any import failure means "not installed"
        status.detail = str(error)
        return status
    status.version = str(getattr(torch, '__version__', '?'))
    try:
        if torch.cuda.is_available():
            status.device = torch.cuda.get_device_name(0)
        else:
            status.detail = 'torch.cuda.is_available() is False'
    except Exception as error:  # noqa: B902
        status.detail = str(error)
    return status


def probe_cupy(import_module: ImportModule = importlib.import_module) -> LibraryStatus:
    """Check CuPy: is it installed, and can it see a CUDA device."""
    status = LibraryStatus('cupy')
    try:
        cupy = import_module('cupy')
    except Exception as error:  # noqa: B902
        status.detail = str(error)
        return status
    status.version = str(getattr(cupy, '__version__', '?'))
    try:
        if cupy.cuda.runtime.getDeviceCount() > 0:
            props = cupy.cuda.runtime.getDeviceProperties(0)
            name = props.get('name', b'?')
            status.device = name.decode() if isinstance(name, bytes) else str(name)
        else:
            status.detail = 'no CUDA device'
    except Exception as error:  # noqa: B902
        status.detail = str(error)
    return status


def probe_tensorrt(import_module: ImportModule = importlib.import_module) -> LibraryStatus:
    """Check the TensorRT Python bindings: installed, and can a builder be created."""
    status = LibraryStatus('tensorrt')
    try:
        trt = import_module('tensorrt')
    except Exception as error:  # noqa: B902
        status.detail = str(error)
        return status
    status.version = str(getattr(trt, '__version__', '?'))
    try:
        logger = trt.Logger(trt.Logger.ERROR)
        builder = trt.Builder(logger)
        status.device = 'available' if builder is not None else None
        if status.device is None:
            status.detail = 'Builder could not be created'
    except Exception as error:  # noqa: B902
        status.detail = str(error)
    return status


def probe(root: str = '/', import_module: ImportModule = importlib.import_module,
          run_command: Callable[[list[str]], str | None] = run) -> GpuReport:
    """
    Collect everything into a GpuReport.

    ``root`` lets tests point the file lookups at a fake filesystem;
    ``import_module`` and ``run_command`` let them stand in fake libraries
    and commands.
    """
    report = GpuReport(
        hostname=socket.gethostname(),
        machine=platform.machine(),
        os_name=parse_os_release(os.path.join(root, 'etc', 'os-release')) or platform.platform(),
        kernel=platform.release(),
        python=f'{platform.python_version()} ({sys.executable})',
    )
    for model_path in ('proc/device-tree/model', 'sys/firmware/devicetree/base/model'):
        report.jetson_model = read_first_line(os.path.join(root, model_path))
        if report.jetson_model:
            break
    report.jetson_linux = parse_jetson_linux(
        read_first_line(os.path.join(root, 'etc', 'nv_tegra_release')))
    if report.is_jetson:
        version = run_command(['dpkg-query', '-W', '-f=${Version}', 'nvidia-jetpack'])
        report.jetpack = version.strip() if version else None
    report.nvcc = find_nvcc(root)
    if report.nvcc:
        report.cuda_toolkit = parse_nvcc_version(run_command([report.nvcc, '--version']))
    report.libraries = [
        probe_torch(import_module),
        probe_cupy(import_module),
        probe_tensorrt(import_module),
    ]
    return report


def main(argv: list[str] | None = None) -> int:
    """Print the report. Exit status 1 with ``--require-gpu`` when no GPU is usable."""
    parser = argparse.ArgumentParser(
        prog='gpu_info', description='Report what GPU acceleration this machine has.')
    parser.add_argument('--require-gpu', action='store_true',
                        help='exit with status 1 if no Python library can see a GPU')
    parser.add_argument('--summary', action='store_true', help='print one line only')
    args = parser.parse_args(argv)
    report = probe()
    if args.summary:
        print(report.summary())
    else:
        print('\n'.join(report.lines()))
    return 1 if args.require_gpu and not report.gpu_available else 0


if __name__ == '__main__':
    sys.exit(main())
