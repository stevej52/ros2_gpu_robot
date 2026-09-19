# Host PC: unattended dual-boot install of Ubuntu 24.04

`autoinstall.yaml` lets the Ubuntu 24.04 desktop installer finish on the
host PC with nobody present, next to the existing Windows 11, and come up
reachable over SSH so the rest of the setup can be done from another computer
on the same network. It is on this branch for now; the machine setup it
belongs with lives in
[robot-environment](https://github.com/stevej52/robot-environment).

The installer fetches the file from this URL (the repository is public):

    https://raw.githubusercontent.com/stevej52/ros2_gpu_robot/claude/hopeful-curie-0svtx5/host-pc/autoinstall.yaml

**Status, 2026-09-19:** done. H2-Host (user steve, 192.168.1.238) runs Ubuntu
24.04.5 next to Windows 11, boots Ubuntu by default with Windows in the
menu, has ROS 2 Jazzy desktop on domain 7 with `~/ros2_ws` built, and passed
the two-machine talker/listener test against the Jetson. The clock and
timezone are set for dual boot. No NVIDIA GPU is present (Intel UHD only),
so GPU nodes cannot be tested on it.

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

### If it reboots into Windows instead

The firmware kept Windows Boot Manager ahead of the new `ubuntu` entry (this
PC did). On this AMI firmware the fix is in the Boot tab under "UEFI NVME
Drive BBS Priorities": set Boot Option #1 to `ubuntu`, then F4 to save. Or
boot Ubuntu once from Windows (Settings, System, Recovery, Advanced startup,
Restart now, Use a device, `ubuntu`) and make it permanent from Ubuntu before
any reboot:

    sudo efibootmgr                         # lists ubuntu and Windows Boot Manager with their numbers
    sudo efibootmgr -o <ubuntu>,<windows>   # e.g. 0002,0000: ubuntu first
    sudo efibootmgr -n <ubuntu>             # also force the very next boot into Ubuntu

## Afterwards, from another computer on the same network

Wait until the machine answers, then log in with steve's account password.
For a helper that has to work unattended, install its key first (asks for
the password once): `ssh-copy-id steve@h2-host.local`.

    ssh steve@h2-host.local

Check the boot order first if the machine came up in Windows once; otherwise
a reboot below strands it in Windows with nobody there.

Everything below needs `sudo`, which asks for the password. Two ways to get
through that with nobody at a keyboard:

- **Password once, no standing rule (preferred).** A helper that has the
  password can run the whole script detached in one SSH command; `sudo -S`
  reads the password from standard input, and the script applies its
  user-level steps to the account that called sudo:

      printf '%s\n' "$PW" | ssh steve@h2-host.local 'sudo -S -p "" bash -c "nohup /home/steve/robot-environment/scripts/install_ros2_jazzy.sh --domain-id 7 --workspace > /home/steve/ros2-install.log 2>&1 &"'

- **Passwordless sudo for the setup.** Apply once (asks for the password
  this one time) and remove the file when the setup is done. This is what
  was used on H2-Host; the rule was removed afterwards.

      echo '%sudo ALL=(ALL:ALL) NOPASSWD:ALL' | sudo tee /etc/sudoers.d/90-nopasswd-sudo
      sudo chmod 0440 /etc/sudoers.d/90-nopasswd-sudo

Then bring the system up to date and run the same ROS 2 script as every other
machine of the robot. Use the same `--domain-id` as the Jetson (7):

    sudo apt update && sudo apt full-upgrade -y && sudo reboot
    # wait a minute, then log in again
    ssh steve@h2-host.local
    git clone https://github.com/stevej52/robot-environment.git ~/robot-environment
    ~/robot-environment/scripts/install_ros2_jazzy.sh --domain-id 7 --workspace

Three dual-boot settings the script does not cover. The third keeps Windows
in the boot menu after future kernel updates regenerate it; without it,
Windows was listed only because the installer happened to detect it:

    sudo timedatectl set-local-rtc 1 --adjust-system-clock   # keep the clock right when switching to Windows
    sudo timedatectl set-timezone America/Los_Angeles        # list with: timedatectl list-timezones
    sudo sed -i 's/^#\?GRUB_DISABLE_OS_PROBER=.*/GRUB_DISABLE_OS_PROBER=false/' /etc/default/grub
    grep -q '^GRUB_DISABLE_OS_PROBER=false' /etc/default/grub || echo 'GRUB_DISABLE_OS_PROBER=false' | sudo tee -a /etc/default/grub
    sudo update-grub                                          # should print "Found Windows Boot Manager"

Check with `~/robot-environment/scripts/check_environment.sh`, then the
two-machine test from robot-environment docs/environment.md section 4 (the
Jetson has to be powered on for it). Known quirk: `check_environment.sh`
reports `ros-jazzy-ros-base` even when the desktop variant is installed;
confirm with `dpkg -l ros-jazzy-desktop` before treating that as a failed
install.

The runbook's alternative script is on the Windows partition; reach it with
`sudo mount -t ntfs3 /dev/nvme0n1p3 /mnt/win` and find it under
`/mnt/win/Users/Steve/Documents/ros2-dual-boot/`. Use one script or the
other, not both.
