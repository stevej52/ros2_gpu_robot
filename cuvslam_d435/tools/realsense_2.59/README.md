# RealSense SDK 2.59.1 beside NVIDIA's 2.56.3 (isaac_vo container)

Built 2026-10-12. Lives in the container's mounted workspace, `/workspaces/isaac_ros-dev/rs259`
(host: `~/workspaces/isaac_ros-dev/rs259`); NVIDIA's librealsense 2.56.3 in `/usr/local` and the
realsense-ros 4.56.3 debs are untouched.

1. `build_librealsense.sh` -> `rs259/prefix`: v2.59.1, RSUSB backend, no CUDA (as NVIDIA's),
   `ENABLE_STATS=OFF` (usage statistics compiled out), `CHECK_FOR_UPDATES=OFF`. ~40 min, -j4.
2. `build_ros.sh` -> `rs259/ws`: realsense-ros 4.59.1 against it. ~8 min. The
   realsense2_camera_msgs definitions are unchanged from 4.56.3, so the splitter needs no rebuild.
3. jetnano_bringup `cuvslam_vo.sh` sources the overlay unless `rs259/OFF` exists.

Needs D435 firmware 5.17.3.10 (`rs259/prefix/bin/rs-fw-update -s <serial> -f
D4XX_FW_Image-5.17.3.10.bin`, with jetnano-robot stopped). On 5.12.10 the depth module does not start.

5.17.3.10 refuses `depth_module.emitter_on_off` before streaming (hwmon 0x7b, -9) but takes it
live and then really alternates; so cuvslam_nvblox_d435.launch.py starts the projector OFF and
jetnano_bringup sensor_sleep's camera keeper switches alternation on once the camera streams.

Checks: `test_cam.sh NAME LIVE_ONOFF [-p ...]` runs the driver alone on domain 55;
`speckle_probe.py [/camera]` prints, per projector flag, how dotted the IR frames are
(2026-10-12 on the bench: off 2.6-2.7, on 2.9-3.0, projector off 2.6).

Rollback: `touch rs259/OFF`, flash `D4XX_FW_Image-5.12.10.0.bin` (kept in `firmware/`), set
emitter_enabled 1 / emitter_on_off True back in the launch.
