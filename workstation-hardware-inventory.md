# Workstation Hardware Inventory

*Last updated: 2026-07-09*

## Motherboard

-   **Model:** ASUS ROG STRIX Z390-E Gaming
-   **BIOS Vendor:** American Megatrends Inc. (AMI)
-   **BIOS Version:** 2102
-   **BIOS Date:** 2024-05-03
-   **Chipset:** Intel Z390

## Processor

-   **CPU:** Intel Core i7-9700K
-   **Microarchitecture:** Coffee Lake Refresh
-   **Cores / Threads:** 8 / 8
-   **Microcode:** 0x104
-   **CPU Signature:** 0x000906ed
-   **Observed Turbo Frequency:** \~4.6 GHz
-   **Base Clock (TSC):** \~3.6 GHz

## Memory

-   **Capacity:** 64 GB
-   **Configuration:** 4 × 16 GB
-   **Model:** Corsair CMW64GX4M4C3200C16
-   **Type:** DDR4
-   **Nominal XMP Speed:** 3200 MT/s
-   **Current Configured Speed:** 2133 MT/s (JEDEC safe mode)
-   **Configured Voltage:** 1.20 V

## Graphics

-   **GPU:** NVIDIA GeForce RTX 2060 (TU106)
-   **Driver:** NVIDIA 595.71.05
-   **OpenGL Renderer:** NVIDIA GeForce RTX 2060/PCIe/SSE2
-   **PCIe Link:** x16 (link training should ideally negotiate Gen3/Gen4
    depending on platform)

## Storage

### System SSD

-   Encrypted LUKS root filesystem
-   LVM logical volumes

### NVMe SSD

-   Samsung SM981 / PM981 / PM983 NVMe
-   Workspace logical volume
-   Docker logical volume

### SATA Data Array

-   2 × SATA drives
-   LVM RAID1
-   Mounted at `/data`
-   Healthy and synchronized

## Networking

-   **Ethernet:** Intel I219-V Gigabit Ethernet

## USB Devices

-   Logitech Unifying Receivers
-   Logitech C310 webcams
-   Plantronics Blackwire C5220 headset
-   YubiKey 4/5
-   CSR Bluetooth USB adapter
-   ASUS Aura motherboard USB controller
-   SanDisk Ultra USB flash drive

## Power Supply

-   **Model:** ASUS ROG Thor 1200 W

## Cooling

-   Air cooling (CPU temperatures observed around 70--73 °C under load)

## Operating System

-   Ubuntu 26.04 LTS
-   Linux Kernel 7.0.0-27-generic

## Storage Layout

``` text
LUKS
 └── LVM (System)
      └── /

NVMe
 ├── /workspace
 └── Docker

SATA RAID1 (LVM RAID)
 └── /data
```

## Current Stable BIOS Configuration

-   AI Overclock Tuner: Auto
-   ASUS MultiCore Enhancement: Disabled (Enforce All Limits)
-   CPU Ratio: Auto
-   Memory running at JEDEC 2133 MT/s while stability testing
-   XMP intentionally disabled
