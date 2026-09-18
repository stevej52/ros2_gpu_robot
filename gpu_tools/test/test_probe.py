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

"""Tests for gpu_tools.probe that need neither a GPU nor ROS 2."""

import os
import stat
import types

from gpu_tools import probe as gpu


def fake_import(modules):
    """Return an import function that only knows the given fake modules."""
    def import_module(name):
        if name in modules:
            return modules[name]
        raise ImportError(f'No module named {name!r}')
    return import_module


def fake_torch(available=True, name='Orin'):
    cuda = types.SimpleNamespace(is_available=lambda: available,
                                 get_device_name=lambda index: name)
    return types.SimpleNamespace(__version__='2.9.0', cuda=cuda)


def fake_cupy(count=1):
    runtime = types.SimpleNamespace(
        getDeviceCount=lambda: count,
        getDeviceProperties=lambda index: {'name': b'Orin'})
    return types.SimpleNamespace(__version__='13.6.0', cuda=types.SimpleNamespace(runtime=runtime))


def jetson_root(tmp_path, with_nvcc=True):
    """Build a fake Jetson filesystem under tmp_path."""
    (tmp_path / 'etc').mkdir()
    (tmp_path / 'etc' / 'nv_tegra_release').write_text(
        '# R39 (release), REVISION: 2.1, GCID: 12345, BOARD: generic, EABI: aarch64, DATE: x\n')
    (tmp_path / 'etc' / 'os-release').write_text(
        'NAME="Ubuntu"\nPRETTY_NAME="Ubuntu 24.04.3 LTS"\n')
    model = tmp_path / 'proc' / 'device-tree'
    model.mkdir(parents=True)
    (model / 'model').write_bytes(b'NVIDIA Jetson Orin Nano Developer Kit Super\x00')
    if with_nvcc:
        nvcc = tmp_path / 'usr' / 'local' / 'cuda' / 'bin' / 'nvcc'
        nvcc.parent.mkdir(parents=True)
        nvcc.write_text('#!/bin/sh\necho "Cuda compilation tools, release 13.2, V13.2.1"\n')
        nvcc.chmod(nvcc.stat().st_mode | stat.S_IEXEC)
    return str(tmp_path)


def commands(jetpack='7.2.1-b10'):
    def run_command(cmd):
        if cmd[0] == 'dpkg-query':
            return jetpack
        if cmd[0].endswith('nvcc'):
            return ('nvcc: NVIDIA (R) Cuda compiler driver\n'
                    'Cuda compilation tools, release 13.2, V13.2.1\n')
        return None
    return run_command


def test_parsers():
    assert gpu.parse_jetson_linux('# R39 (release), REVISION: 2.1, GCID: 1') == '39.2.1'
    assert gpu.parse_jetson_linux('# R36 (release), REVISION: 4.3') == '36.4.3'
    assert gpu.parse_jetson_linux('') is None
    assert gpu.parse_jetson_linux(None) is None
    assert gpu.parse_nvcc_version('Cuda compilation tools, release 13.2, V13.2.1') == '13.2'
    assert gpu.parse_nvcc_version('garbage') is None


def test_jetson_with_everything(tmp_path, monkeypatch):
    monkeypatch.setattr(gpu.shutil, 'which', lambda name: None)
    root = jetson_root(tmp_path)
    report = gpu.probe(root, fake_import({'torch': fake_torch(), 'cupy': fake_cupy()}), commands())
    assert report.is_jetson
    assert report.jetson_model == 'NVIDIA Jetson Orin Nano Developer Kit Super'
    assert report.jetson_linux == '39.2.1'
    assert report.jetpack == '7.2.1-b10'
    assert report.os_name == 'Ubuntu 24.04.3 LTS'
    assert report.cuda_toolkit == '13.2'
    assert report.nvcc == os.path.join(root, 'usr', 'local', 'cuda', 'bin', 'nvcc')
    assert report.gpu_available
    names = {lib.name: lib for lib in report.libraries}
    assert names['torch'].device == 'Orin'
    assert names['cupy'].device == 'Orin'
    assert not names['tensorrt'].installed
    assert 'torch on Orin' in report.summary()
    lines = report.lines()
    assert any(line.startswith('jetson linux: 39.2.1') for line in lines)
    assert lines[-1].startswith('gpu:') and lines[-1].endswith('yes')


def test_plain_pc_without_anything(tmp_path, monkeypatch):
    monkeypatch.setattr(gpu.shutil, 'which', lambda name: None)
    (tmp_path / 'etc').mkdir()
    report = gpu.probe(str(tmp_path), fake_import({}), lambda cmd: None)
    assert not report.is_jetson
    assert report.cuda_toolkit is None
    assert not report.gpu_available
    assert all(not lib.installed for lib in report.libraries)
    assert 'no Python library can see a GPU' in report.summary()
    lines = report.lines()
    assert not any(line.startswith('jetson') for line in lines)
    assert 'cuda toolkit: not found' in lines
    assert 'torch: not installed' in lines


def test_torch_installed_but_no_gpu(tmp_path, monkeypatch):
    monkeypatch.setattr(gpu.shutil, 'which', lambda name: None)
    (tmp_path / 'etc').mkdir()
    report = gpu.probe(str(tmp_path), fake_import({'torch': fake_torch(available=False)}),
                       lambda cmd: None)
    torch = report.libraries[0]
    assert torch.installed and not torch.has_gpu
    assert torch.describe() == 'torch 2.9.0: no GPU (torch.cuda.is_available() is False)'
    assert not report.gpu_available


def test_broken_library_does_not_crash():
    def import_module(name):
        raise RuntimeError('libcudart.so.13: cannot open shared object file')
    status = gpu.probe_torch(import_module)
    assert not status.installed
    assert 'libcudart' in status.detail


def test_main_exit_codes(monkeypatch, capsys):
    monkeypatch.setattr(gpu.shutil, 'which', lambda name: None)
    monkeypatch.setattr(gpu, 'probe', lambda: gpu.GpuReport(
        hostname='pc', machine='x86_64', os_name='Ubuntu', kernel='7.0', python='3.12'))
    assert gpu.main([]) == 0
    assert 'gpu:' in capsys.readouterr().out
    assert gpu.main(['--require-gpu']) == 1
    capsys.readouterr()
    assert gpu.main(['--summary']) == 0
    assert capsys.readouterr().out.strip() == 'pc: no Python library can see a GPU'
