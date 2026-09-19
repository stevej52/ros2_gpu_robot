# Host PC: unattended dual-boot install of Ubuntu 24.04

`autoinstall.yaml` lets the Ubuntu 24.04 desktop installer finish on the
host PC with nobody present, next to the existing Windows 11, and come up
reachable over SSH so the rest of the setup can be done from another computer
on the same network. It is on this branch for now; the machine setup it
belongs with lives in
[robot-environment](https://github.com/stevej52/robot-environment).

The installer fetches the file from this URL (the repository is public):

    https://raw.githubusercontent.com/stevej52/ros2_gpu_robot/claude/hopeful-curie-0svtx5/host-pc/autoinstall.yaml

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

## Afterwards, from another computer on the network

    ssh <username>@<computer-name>.local

Log in with the account password. `sudo` asks for it once per session; to
let an unattended helper run the install script without a prompt, apply this
once yourself, then remove the file when the setup is done:

    echo '%sudo ALL=(ALL:ALL) NOPASSWD:ALL' | sudo tee /etc/sudoers.d/90-nopasswd-sudo
    sudo chmod 0440 /etc/sudoers.d/90-nopasswd-sudo

Then run the ROS 2 install script from robot-environment (or the runbook's
script from the Windows partition, mounted with
`sudo mount -t ntfs3 /dev/nvme0n1p3 /mnt/win`), set the timezone with
`timedatectl`, and apply the dual-boot clock fix:

    sudo timedatectl set-local-rtc 1 --adjust-system-clock
