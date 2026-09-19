# Host PC: unattended dual-boot install of Ubuntu 24.04

`autoinstall.yaml` lets the Ubuntu 24.04 desktop installer finish on the
host PC with nobody present, next to the existing Windows 11, and come up
reachable over SSH so the rest of the setup can be done from another computer
on the same network. It is on this branch for now; the machine setup it
belongs with lives in
[robot-environment](https://github.com/stevej52/robot-environment).

The installer fetches the file from this URL (the repository is public):

    https://raw.githubusercontent.com/stevej52/ros2_gpu_robot/claude/hopeful-curie-0svtx5/host-pc/autoinstall.yaml

Install started 2026-09-19 with computer name **H2-Host** and user **steve**.

## At the host PC

1. Plug in the Ethernet cable and the Ubuntu stick. In Windows: Settings,
   System, Recovery, Advanced startup, Restart now, Use a device, the stick.
2. When the stick's boot menu appears, press a key so it does not boot on its
   own. With "Try or Install Ubuntu" highlighted press `e`, add a space and
   `noprompt` at the end of the line that starts with `linux`, then press F10.
3. Language, accessibility, keyboard, network as usual. Skip the installer
   update if offered.
4. "How would you like to install Ubuntu?": Automated installation. Enter the
   URL above, click Validate.
5. Disk page: Install Ubuntu alongside Windows Boot Manager. It uses the free
   space (about 322 GB). Never Erase disk.
6. Account page: name, computer name, username, password. The computer name
   is what the other machines connect to, as `<name>.local`.
7. Check the summary says alongside Windows, click Install, leave.

The machine installs, reboots by itself, and boots Ubuntu with the SSH
server running. Nothing on the stick changes for this; it is the stock ISO.

## Afterwards, from another computer on the same network

Wait until the machine answers, then log in with steve's account password:

    ssh steve@h2-host.local

Steve chose passwordless sudo for the setup, so an unattended helper can run
the script below without a prompt. Apply it once (it asks for the password
this one time), and remove the file when the setup is done:

    echo '%sudo ALL=(ALL:ALL) NOPASSWD:ALL' | sudo tee /etc/sudoers.d/90-nopasswd-sudo
    sudo chmod 0440 /etc/sudoers.d/90-nopasswd-sudo

Then bring the system up to date and run the same ROS 2 script as every other
machine of the robot. Use the same `--domain-id` as the Jetson (the docs use
7 as the example):

    sudo apt update && sudo apt full-upgrade -y && sudo reboot
    # wait a minute, then log in again
    ssh steve@h2-host.local
    git clone https://github.com/stevej52/robot-environment.git ~/robot-environment
    ~/robot-environment/scripts/install_ros2_jazzy.sh --domain-id 7 --workspace

Two dual-boot settings the script does not cover:

    sudo timedatectl set-local-rtc 1 --adjust-system-clock   # keep the clock right when switching to Windows
    sudo timedatectl set-timezone <zone>                     # e.g. America/Denver; list with: timedatectl list-timezones

Check with `~/robot-environment/scripts/check_environment.sh`, then the
two-machine test from robot-environment docs/environment.md section 4.

The runbook's alternative script is on the Windows partition; reach it with
`sudo mount -t ntfs3 /dev/nvme0n1p3 /mnt/win` and find it under
`/mnt/win/Users/Steve/Documents/ros2-dual-boot/`. Use one script or the
other, not both.

If Windows is missing from the boot menu afterwards: set
`GRUB_DISABLE_OS_PROBER=false` in `/etc/default/grub` and run
`sudo update-grub`.
