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

"""Tests for gpu_tools.load that need neither a Jetson nor ROS 2."""

from gpu_tools import load

# What tegrastats prints on JetPack 5 (Orin, two GPU entries, two cores off) ...
JETPACK5 = ('RAM 3821/7337MB (lfb 21x1MB) SWAP 1/3668MB (cached 0MB) '
            'CPU [30%@1651,53%@1651,70%@1651,30%@1651,off,off] '
            'EMC_FREQ 0% GR3D_FREQ 0% GR3D2_FREQ 0%@0 cpu@45.5C gpu@44.9C')
# ... on JetPack 6 (one GPU entry with a frequency per cluster) ...
JETPACK6 = ('RAM 9873/30697MB (lfb 76x4MB) '
            'CPU [1%@729,0%@729,0%@729,0%@729,0%@1728,0%@1728,100%@1728,0%@1728] '
            'EMC_FREQ 6%@2133 GR3D_FREQ 0%@[0,0]')
# ... and on an Orin Nano Super with the power rails.
ORIN_NANO = ('09-19-2026 10:00:00 RAM 3011/7620MB (lfb 4x4MB) SWAP 0/3810MB (cached 0MB) '
             'CPU [12%@1510,8%@1510,3%@1510,1%@1510,0%@1510,0%@1510] GR3D_FREQ 37%@[612] '
             'cpu@45.5C soc2@44.8C soc0@45C gpu@44.9C tj@45.5C soc1@45.1C '
             'VDD_IN 4952mW/4952mW VDD_CPU_GPU_CV 1084mW/1084mW VDD_SOC 1443mW/1443mW')


def test_jetpack5_line():
    sample = load.parse_tegrastats(JETPACK5)
    assert sample.source == 'tegrastats'
    assert (sample.mem_used_mb, sample.mem_total_mb) == (3821, 7337)
    assert (sample.swap_used_mb, sample.swap_total_mb) == (1, 3668)
    assert sample.cpu_cores == [30, 53, 70, 30, None, None]
    assert sample.cpu_percent == (30 + 53 + 70 + 30) / 4
    assert sample.gpu_percent == 0
    assert sample.gpu_freq_mhz is None
    assert (sample.cpu_temp_c, sample.gpu_temp_c) == (45.5, 44.9)
    assert sample.power_mw is None


def test_jetpack6_line():
    sample = load.parse_tegrastats(JETPACK6)
    assert sample.mem_total_mb == 30697
    assert sample.swap_total_mb is None
    assert len(sample.cpu_cores) == 8 and sample.cpu_cores[6] == 100
    assert sample.cpu_percent == 101 / 8
    assert (sample.gpu_percent, sample.gpu_freq_mhz) == (0, 0)


def test_orin_nano_line():
    sample = load.parse_tegrastats(ORIN_NANO)
    assert (sample.gpu_percent, sample.gpu_freq_mhz) == (37, 612)
    assert sample.power_mw == 4952
    assert (sample.cpu_temp_c, sample.gpu_temp_c) == (45.5, 44.9)
    assert round(sample.mem_percent, 1) == round(100 * 3011 / 7620, 1)
    assert sample.raw == ORIN_NANO


def test_summary_and_key_values():
    sample = load.parse_tegrastats(ORIN_NANO)
    assert sample.summary() == ('cpu 4%  gpu 37%  mem 3011/7620MB (40%)  swap 0/3810MB  '
                                'gpu 45C  cpu 46C  5.0W')
    values = dict(sample.key_values())
    assert values['gpu_percent'] == '37'
    assert values['cpu_cores_percent'] == '12,8,3,1,0,0'
    assert values['swap_used_mb'] == '0'


def test_unreadable_line_gives_empty_sample():
    sample = load.parse_tegrastats('tegrastats: not running as root, some fields missing')
    assert sample.cpu_percent is None and sample.gpu_percent is None
    assert sample.mem_total_mb is None
    assert sample.summary() == 'cpu -  gpu -'
    assert dict(sample.key_values())['cpu_cores_percent'] == '-'


def fake_proc(tmp_path, busy, total):
    """Write a /proc with two cores whose 'cpu' line has the given busy/idle split."""
    proc = tmp_path / 'proc'
    proc.mkdir(exist_ok=True)
    idle = total - busy
    (proc / 'stat').write_text(
        f'cpu  {busy} 0 0 {idle} 0 0 0 0 0 0\n'
        f'cpu0 {busy} 0 0 {idle} 0 0 0 0 0 0\n'
        f'cpu1 0 0 0 {total} 0 0 0 0 0 0\n'
        'intr 1 2 3\nctxt 4\n')
    (proc / 'meminfo').write_text(
        'MemTotal:        8000000 kB\nMemFree:         1000000 kB\n'
        'MemAvailable:    4000000 kB\nSwapTotal:       2000000 kB\nSwapFree:        1500000 kB\n')


def test_proc_sampler_measures_the_delta(tmp_path):
    fake_proc(tmp_path, busy=100, total=1000)
    sampler = load.ProcSampler(root=str(tmp_path))
    fake_proc(tmp_path, busy=350, total=1500)      # +250 busy of +500 total
    sample = sampler.sample()
    assert sample.source == 'proc'
    assert sample.cpu_percent == 50
    assert sample.cpu_cores == [50, 0]
    assert sample.gpu_percent is None
    assert sample.mem_total_mb == 8000000 / 1024
    assert sample.mem_used_mb == (8000000 - 4000000) / 1024
    assert sample.swap_used_mb == (2000000 - 1500000) / 1024
    assert sample.summary().startswith('cpu 50%  gpu -  mem ')


def test_proc_sampler_on_this_machine():
    sampler = load.ProcSampler()
    sample = sampler.sample()
    assert sample.mem_total_mb and sample.mem_total_mb > 0
    assert sample.cpu_percent is None or 0 <= sample.cpu_percent <= 100


def test_average_takes_mean_of_rates_and_max_of_memory():
    first = load.parse_tegrastats(ORIN_NANO)
    second = load.parse_tegrastats(ORIN_NANO.replace('GR3D_FREQ 37%', 'GR3D_FREQ 63%')
                                   .replace('RAM 3011/', 'RAM 4000/'))
    mean = load.average([first, second])
    assert mean.gpu_percent == 50
    assert mean.mem_used_mb == 4000
    assert mean.mem_total_mb == 7620


def test_make_sampler_rejects_unknown_source():
    try:
        load.make_sampler('gpu-z')
    except ValueError as error:
        assert 'gpu-z' in str(error)
    else:
        raise AssertionError('no error for an unknown source')


def test_main_prints_lines_and_average(capsys):
    assert load.main(['--source', 'proc', '--samples', '2', '--interval', '0.05']) == 0
    out = capsys.readouterr().out.splitlines()
    assert len(out) == 3
    assert out[0].strip().startswith('0.1s') or out[0].strip().startswith('0.0s')
    assert out[-1].startswith('average of 2:')
